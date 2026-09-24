# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,06b Lakebase RAGクエリ: ゴール体験（代替パターン）
# MAGIC %md
# MAGIC # 06b_rag_query_lakebase: 自然言語検索 → 仕様・図・波形の即時表示（Lakebase 版）
# MAGIC
# MAGIC ## 目的
# MAGIC **06_rag_query の代替パターンです。**
# MAGIC 検索バックエンドを AI Search (Vector Search) から **Lakebase Search (pgvector)** に
# MAGIC 差し替えただけで、RAG の体験は同じであることを確認します。
# MAGIC
# MAGIC ## 所要時間目安: 15分
# MAGIC
# MAGIC ## 前提
# MAGIC - 05b ノートブックが実行済み（Lakebase にチャンク＋埋め込みがロード済み）
# MAGIC
# MAGIC ## 06 との差分（ここが学習ポイント）
# MAGIC | 処理 | 06 (Vector Search) | 06b (Lakebase) |
# MAGIC |---|---|---|
# MAGIC | 質問のベクトル化 | 不要（マネージド） | 自分で埋め込み API を呼ぶ |
# MAGIC | 検索 | `w.vector_search_indexes.query_index` | SQL: `ORDER BY embedding <=> ...` |
# MAGIC | フィルタ | `filters` 引数 | 普通の `WHERE` 句（SQL の表現力） |
# MAGIC | ハイブリッド検索 | BM25 は別機能 | ベクトル + 全文検索を RRF で合成可能 |
# MAGIC
# MAGIC LLM による回答生成・図/波形の表示ロジックは **06 と完全に同一** です。
# MAGIC → 「検索レイヤーだけが差し替え可能」というアーキテクチャ上の分離を体感できます。

# COMMAND ----------

# DBTITLE 1,ライブラリ・設定
# MAGIC %pip install "psycopg[binary]>=3.1" openai --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Lakebase 接続・検索関数の定義
# ==============================================================
# Lakebase 接続ヘルパー + 検索関数
# ==============================================================
from databricks.sdk import WorkspaceClient
import psycopg, openai, time, re

w = WorkspaceClient()

def pg_api(method, path, body=None, query=None):
    return w.api_client.do(method, f"/api/2.0/postgres{path}", body=body, query=query)

def get_lakebase_host():
    ep = pg_api("GET", f"/{LAKEBASE_ENDPOINT_PATH}")
    return ep["status"]["hosts"]["host"]

def get_lakebase_token():
    cred = pg_api("POST", "/credentials", body={"endpoint": LAKEBASE_ENDPOINT_PATH})
    return cred["token"]

def get_conn():
    """Lakebase への新規接続（呼ぶたびにトークン再取得 → 1時間失効を回避）"""
    return psycopg.connect(
        host=get_lakebase_host(),
        dbname=LAKEBASE_PG_DATABASE,
        user=w.current_user.me().user_name,
        password=get_lakebase_token(),
        sslmode="require",
        autocommit=True,
    )

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
client = openai.OpenAI(
    api_key=ctx.apiToken().get(),
    base_url=f"{ctx.apiUrl().get()}/serving-endpoints",
)

def embed_texts(texts):
    resp = client.embeddings.create(model=EMBEDDING_ENDPOINT, input=texts)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]

def to_vector_literal(vec):
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"

# lakebase_text (BM25) 拡張の有無を判定（ハイブリッド検索の切り替え用）
with get_conn() as conn:
    BM25_AVAILABLE = conn.execute(
        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'lakebase_text'"
    ).fetchone()[0] > 0
print(f"✅ Lakebase 接続準備完了 (BM25 拡張: {'有効' if BM25_AVAILABLE else '無効 → ts_rank を使用'})")

# COMMAND ----------

# DBTITLE 1,検索関数: ベクトル検索 & ハイブリッド検索
# ==============================================================
# 検索関数: ベクトル検索 / ハイブリッド検索 (RRF)
# ==============================================================
def search_chunks(question, num_results=5):
    """
    ベクトル類似検索: 質問を埋め込み、コサイン距離で近いチャンクを取得。
    06 の query_index(query_text=...) に相当。
    """
    qvec_str = to_vector_literal(embed_texts([question])[0])
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT chunk_id, doc_id, content, product_ids_str, file_path,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""",
            (qvec_str, qvec_str, num_results),
        ).fetchall()
    return rows

def extract_text_query(question):
    """
    全文検索用のクエリ文字列を質問から抽出する。

    日本語の質問文をそのまま plainto_tsquery に渡すと、助詞が語に結合して
    トークン化され（例: 「の過渡応答」が1トークン）、本文側と一致せず 0 件になる。
    そのため製品ID (SNS-200 等)・英数トークンを抽出して全文検索に使う。
    （実機検証済み: 生の日本語質問は 0 件、製品ID抽出なら正しくヒット）
    """
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-_.]*", question)
    return " ".join(tokens)

def search_chunks_hybrid(question, num_results=5, rrf_k=60, per_rank_limit=40):
    """
    ハイブリッド検索: ベクトル検索 + 全文検索を RRF (Reciprocal Rank Fusion) で合成。

    製造業実務: 「SNS-200 過渡応答」のような製品ID入りの質問では、
    意味の近さ（ベクトル）だけでなく、製品IDの厳密一致（全文検索）も効かせたい。
    → 両者のランクを RRF で合成すると両方の強みを活かせる。
    """
    text_query = extract_text_query(question)
    if not text_query:
        # 英数トークンが無ければ全文検索は機能しない → ベクトル検索のみ
        print("   (英数トークンなし → ベクトル検索のみで実行)")
        return search_chunks(question, num_results)
    print(f"   全文検索クエリ: '{text_query}'")

    qvec_str = to_vector_literal(embed_texts([question])[0])
    if BM25_AVAILABLE:
        # Lakebase Search の BM25（docs 記載の <@> 演算子。小さいほど関連）
        text_score = "content_tsv <@> to_bm25query(to_tsvector('simple', %(q)s), %(bm25_idx)s)"
        text_order = "ASC"
        extra_params = {"bm25_idx": f"idx_{LAKEBASE_TABLE_CHUNKS}_bm25"}
    else:
        # 標準 ts_rank による全文検索スコア（大きいほど関連）
        text_score = "ts_rank(content_tsv, plainto_tsquery('simple', %(q)s))"
        text_order = "DESC"
        extra_params = {}

    sql = f"""
        WITH vec AS (
            SELECT chunk_id,
                   RANK() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS r
            FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            ORDER BY embedding <=> %(qvec)s::vector
            LIMIT %(per)s
        ),
        txt AS (
            SELECT chunk_id,
                   RANK() OVER (ORDER BY {text_score} {text_order}) AS r
            FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            WHERE content_tsv @@ plainto_tsquery('simple', %(q)s)
            ORDER BY {text_score} {text_order}
            LIMIT %(per)s
        )
        SELECT c.chunk_id, c.doc_id, c.content, c.product_ids_str, c.file_path,
               COALESCE(1.0/(%(k)s + vec.r), 0) + COALESCE(1.0/(%(k)s + txt.r), 0) AS rrf_score
        FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS} c
        JOIN vec ON vec.chunk_id = c.chunk_id
        LEFT JOIN txt ON txt.chunk_id = c.chunk_id
        UNION ALL
        SELECT c.chunk_id, c.doc_id, c.content, c.product_ids_str, c.file_path,
               COALESCE(1.0/(%(k)s + vec.r), 0) + COALESCE(1.0/(%(k)s + txt.r), 0) AS rrf_score
        FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS} c
        JOIN txt ON txt.chunk_id = c.chunk_id
        LEFT JOIN vec ON vec.chunk_id = c.chunk_id
        WHERE vec.chunk_id IS NULL
        ORDER BY rrf_score DESC
        LIMIT %(n)s
    """
    params = {"qvec": qvec_str, "q": text_query, "k": rrf_k, "per": per_rank_limit, "n": num_results}
    params.update(extra_params)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows

print("✅ 検索関数定義完了: search_chunks() / search_chunks_hybrid()")

# COMMAND ----------

# DBTITLE 1,RAG検索関数の定義
# ==============================================================
# RAG 検索関数: 自然言語 → 検索 → 回答 → 図・波形表示
# ==============================================================
# ※ extract_direct_answer / answer() のロジックは 06_rag_query と同一。
#   違いは「検索ヒットの取得方法」だけ（query_index → Lakebase SQL）。
import os, re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image as PILImage
import csv as csv_mod
import numpy as np

def extract_direct_answer(question: str, hits):
    """
    仕様値のような事実質問は、LLM に頼らず検索ヒットから直接抽出する。
    Free Edition のガードレール誤検知時でも確実に答えられるようにする。
    """
    q = question.lower()
    patterns = []
    field_name = None

    if "動作温度" in question or "温度範囲" in question or "operating temp" in q:
        field_name = "動作温度範囲"
        patterns = [
            r"動作温度(?:範囲)?[:：]\s*([-+]?\d+\s*~\s*[-+]?\d+\s*°?C)",
            r"Operating Temp[:：]\s*([-+]?\d+\s*~\s*[-+]?\d+\s*°?C)",
            r"Temp\s+([-+]?\d+\s*~\s*[-+]?\d+\s*°?C)",
        ]
    elif "供給電圧" in question or "電圧" in question or "supply voltage" in q:
        field_name = "供給電圧"
        patterns = [
            r"供給電圧[:：]\s*([0-9.]+\s*~\s*[0-9.]+V)",
            r"Supply Voltage[:：]\s*([0-9.]+\s*~\s*[0-9.]+V)",
        ]
    elif "応答時間" in question or "response time" in q:
        field_name = "応答時間"
        patterns = [
            r"応答時間[:：]\s*([0-9.]+\s*ms)",
            r"Response Time[:：]\s*([0-9.]+\s*ms)",
        ]
    elif "精度" in question or "accuracy" in q:
        field_name = "精度"
        patterns = [
            r"精度[:：]\s*([^\n]+)",
            r"Accuracy[:：]\s*([^\n]+)",
        ]

    if not patterns:
        return None

    for h in hits:
        doc_id = h[1]
        content = h[2] or ""
        for p in patterns:
            m = re.search(p, content, flags=re.IGNORECASE)
            if m:
                value = m.group(1).strip()
                return {
                    "field": field_name,
                    "value": value,
                    "doc_id": doc_id,
                }
    return None

def answer(question: str, num_results: int = 5, hybrid: bool = False):
    """
    自然言語で問い合わせると、関連する仕様・図・波形が即座に表示される。
    hybrid=True でベクトル+全文検索のハイブリッド検索（RRF）に切り替わる。
    """
    print(f"\n{'='*60}")
    print(f"🔍 質問: {question}")
    print(f"   検索方式: {'ハイブリッド (ベクトル+全文 RRF)' if hybrid else 'ベクトル (Lakebase)'}")
    print(f"{'='*60}")

    # --- Step 1: Lakebase で検索（06 では query_index だった部分）---
    try:
        if hybrid:
            hits = search_chunks_hybrid(question, num_results)
        else:
            hits = search_chunks(question, num_results)
        print(f"\n📚 検索ヒット: {len(hits)} 件")
    except Exception as e:
        print(f"\n⚠️ Lakebase 検索エラー: {e}")
        print("→ 05b ノートブックが実行済みか確認してください。")
        return

    if not hits:
        print("検索結果がありません。")
        return

    # 仕様値のような事実質問は検索ヒットから直接抽出
    direct_answer = extract_direct_answer(question, hits)
    if direct_answer:
        print(f"\n💬 直接回答:")
        print(f"{direct_answer['field']}: {direct_answer['value']}")
        print(f"出典: {direct_answer['doc_id']}")

    # --- Step 2: 関連メディアアセットの収集 ---
    hit_doc_ids = list(set([h[1] for h in hits]))  # doc_id
    hit_product_ids = set()
    for h in hits:
        if h[3]:  # product_ids_str
            hit_product_ids.update(h[3].split(','))

    # media_assets から関連図・波形を取得
    if hit_product_ids:
        pid_filter = " OR ".join([f"product_id = '{p}'" for p in hit_product_ids])
        media_df = spark.sql(f"SELECT * FROM {FQ_MEDIA_ASSETS} WHERE {pid_filter}")
        media_rows = media_df.collect()
    else:
        media_rows = []

    # --- Step 3: LLM による回答生成 ---
    # 直接回答できた場合は LLM をスキップして、誤検知や余計な要約を避ける
    if not direct_answer:
        context = "\n---\n".join([h[2][:500] for h in hits])  # content
        sources = ", ".join(hit_doc_ids[:5])

        try:
            response = client.chat.completions.create(
                model=LLM_ENDPOINT,
                messages=[
                    {"role": "system", "content": "あなたは製造業の技術ドキュメントに基づいて回答するアシスタントです。日本語で回答し、出典ファイル名を明記してください。"},
                    {"role": "user", "content": f"質問: {question}\n\n参考情報:\n{context}\n\n出典: {sources}"}
                ],
                max_tokens=500,
                temperature=0.1
            )
            answer_text = response.choices[0].message.content
            print(f"\n💬 回答:")
            print(answer_text)
        except Exception as e:
            error_str = str(e)
            if "guardrail" in error_str.lower():
                print(f"\n⚠️ LLM ガードレール発動（製造業用語の誤検知）")
                print("   → pay-per-token エンドポイントのコンテンツフィルタが")
                print("     技術用語を誤ってブロックしました。")
                print("   → 実運用では専用エンドポイントでガードレール設定を調整します。")
            else:
                print(f"\n⚠️ LLM エラー: {e}")
            print("\n💬 フォールバック: 検索結果から関連情報を直接表示します")
            print("-" * 40)
            for h in hits[:3]:
                print(f"\n📄 {h[1]}:")
                print(f"   {h[2][:200]}...")

    # --- Step 4: 出典ファイル・図・波形の表示 ---
    print(f"\n📁 出典ファイル:")
    for doc_id in hit_doc_ids[:5]:
        print(f"  ・{doc_id}")

    # ブロック図表示
    block_diagrams = [m for m in media_rows if m.asset_type == "block_diagram"]
    if block_diagrams:
        print(f"\n🖼️ ブロック図 ({len(block_diagrams)} 件):")
        for bd in block_diagrams[:2]:
            thumb = bd.thumbnail_path
            if thumb and os.path.exists(thumb):
                img = PILImage.open(thumb)
                display(img)
                print(f"  {bd.source_file_name} (product: {bd.product_id})")

    # 波形チャート表示
    waveform_charts = [m for m in media_rows if m.asset_type == "waveform_chart"]
    if waveform_charts:
        print(f"\n📈 波形チャート ({len(waveform_charts)} 件):")
        for wc in waveform_charts[:2]:
            if os.path.exists(wc.file_path):
                img = PILImage.open(wc.file_path)
                display(img)
                print(f"  {wc.description}")

    # 波形CSVプロット
    waveform_csvs = [m for m in media_rows if m.asset_type == "waveform_csv"]
    if waveform_csvs:
        print(f"\n📉 波形データプロット ({len(waveform_csvs)} 件):")
        for wcsv in waveform_csvs[:2]:
            if os.path.exists(wcsv.file_path):
                try:
                    with open(wcsv.file_path, 'r') as f:
                        reader = csv_mod.reader(f)
                        rows = list(reader)
                    if len(rows) > 2:
                        header = rows[0]
                        data = np.array([[float(x) for x in r] for r in rows[1:]])
                        fig, ax = plt.subplots(figsize=(6, 3))
                        ax.plot(data[:, 0], data[:, 1], 'b-', lw=0.8)
                        ax.set_xlabel(header[0]); ax.set_ylabel(header[1])
                        ax.set_title(f"波形 - {wcsv.product_id}", fontsize=10)
                        ax.grid(True, alpha=0.3)
                        plt.tight_layout()
                        display(fig)
                        plt.close(fig)
                except Exception as plot_err:
                    print(f"  プロットエラー: {plot_err}")

    print(f"\n{'='*60}")
    print("✅ 検索完了")

print("✅ answer() 関数定義完了")
print("以下のセルでデモ質問を実行してください。")

# COMMAND ----------

# DBTITLE 1,デモ質問 1: SNS-200 過渡応答
# ==============================================================
# デモ質問 1: 製品の試験結果と波形を確認
# ==============================================================
# 製造業実務: 「あの製品の過渡応答はどうだった？」という典型的な問い
answer("SNS-200 の過渡応答の試験結果と波形を見せて")

# COMMAND ----------

# DBTITLE 1,デモ質問 2: 仕様確認
# ==============================================================
# デモ質問 2: 仕様の確認（根拠ドキュメント付き）
# ==============================================================
# 製造業実務: 「この製品の動作温度は？」という技術確認
answer("SNS-100 の動作温度範囲は？根拠となる仕様書も教えて")

# COMMAND ----------

# DBTITLE 1,デモ質問 3: メタデータ抽出の価値
# ==============================================================
# デモ質問 3: メタデータ抽出の価値を体感
# ==============================================================
# 製造業実務: 「修正された測定値があるファイル」を知りたい
# → 取り消し線検出のメタデータがあるからこそ答えられる
answer("取り消し線で修正された測定値を含むファイルはどれ？")

# COMMAND ----------

# DBTITLE 1,おまけ: ハイブリッド検索（ベクトル + 全文 RRF）
# ==============================================================
# ハイブリッド検索の体験
# ==============================================================
# 製品IDのような「厳密に一致させたいキーワード」と
# 「意味の近さ」の両方を効かせたい場面で有効。
# Lakebase Search (lakebase_text) 有効時は BM25、無効時は ts_rank を使用。
answer("SNS-200 の過渡応答の試験結果と波形を見せて", hybrid=True)

# COMMAND ----------

# DBTITLE 1,比較まとめ
# MAGIC %md
# MAGIC ## 06 (Vector Search) との比較まとめ
# MAGIC
# MAGIC | 観点 | 06: Vector Search | 06b: Lakebase Search |
# MAGIC |---|---|---|
# MAGIC | セットアップ | エンドポイント + インデックス作成（10〜20分待ち） | プロジェクト作成 + SQL（数分） |
# MAGIC | データ同期 | Delta Sync（自動・CDF ベース） | 自分でロード（同期はアプリ側の責任） |
# MAGIC | 検索の自由度 | query_text + filters | 任意の SQL（JOIN・WHERE・集計と自由に組合せ） |
# MAGIC | ハイブリッド検索 | インデックスの BM25 対応に依存 | BM25/tsvector を同一クエリで合成可能 |
# MAGIC | 向いている用途 | 大規模・運用レスなセマンティック検索 | OLTP アプリ統合・低遅延・SQL 中心の検索 |
# MAGIC
# MAGIC **次のパターン**: `06c_agent_memory_rag` では、この Lakebase 検索に
# MAGIC **Agent Memory**（会話の記憶）を組み合わせたエージェント型 RAG を体験できます。
