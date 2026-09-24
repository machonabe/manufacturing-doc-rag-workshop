# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,05b Lakebase インデックス: 紹介
# MAGIC %md
# MAGIC # 05b_lakebase_index: Lakebase Search インデックス構築
# MAGIC
# MAGIC ## 目的
# MAGIC - **05_vector_index の代替パターン**: AI Search (Vector Search) を使わず、
# MAGIC   **Lakebase Search**（Lakebase = Databricks マネージド Postgres 上の検索拡張）で
# MAGIC   セマンティック検索基盤を構築する
# MAGIC - `doc_chunks` テーブルを Lakebase にロードし、埋め込みベクトルを付与
# MAGIC - ANN インデックス（`lakebase_ann`。未導入環境では pgvector HNSW にフォールバック）
# MAGIC
# MAGIC ## 所要時間目安: 5〜10分
# MAGIC
# MAGIC ## 前提
# MAGIC - **有償ワークスペース**（Lakebase は Free Edition では利用不可）
# MAGIC - 04 ノートブック実行済み（`doc_chunks` テーブルが存在）
# MAGIC - Lakebase プロジェクト作成権限（なければ既存プロジェクト ID を `00_config` に設定）
# MAGIC
# MAGIC ## Lakebase Search について
# MAGIC プロジェクトの Settings → **Lakebase Search** を有効化すると、
# MAGIC 以下の Postgres 拡張が利用可能になります（有効化は不可逆・コンピュート再起動あり）:
# MAGIC - `lakebase_vector`: 大規模対応の ANN ベクトル検索（`lakebase_ann` インデックス）
# MAGIC - `lakebase_text`: BM25 全文検索（`lakebase_bm25` インデックス）
# MAGIC
# MAGIC **このノートブックは未導入環境でも動きます**（標準 pgvector + HNSW に自動フォールバック）。
# MAGIC Lakebase Search 有効化後に再実行すると `lakebase_ann` / `lakebase_bm25` を使います。
# MAGIC
# MAGIC ## 05 (Vector Search) との違い
# MAGIC | 観点 | 05: Vector Search | 05b: Lakebase Search |
# MAGIC |---|---|---|
# MAGIC | インデックス管理 | フルマネージド (Delta Sync) | 自分で DDL / ロードを管理 |
# MAGIC | ベクトル化 | マネージドエンベディング（自動） | 自分で埋め込み API を呼ぶ |
# MAGIC | 検索 API | `query_index` | SQL (`<=>` / `<@>` 演算子) |
# MAGIC | 強み | 運用ゼロ・自動同期 | OLTP 統合・BM25 ハイブリッド・SQL の自由度 |
# MAGIC
# MAGIC ## 製造業における Lakebase の価値
# MAGIC 検索基盤が「普通の Postgres」になることで、設計変更管理・保守ポータルなど
# MAGIC **既存の OLTP アプリケーションと同じ DB 上で**セマンティック検索を提供できます。
# MAGIC ベクトル検索と通常の SQL フィルタ（製品ID・日付・承認ステータス等）を
# MAGIC 1 クエリに混ぜられるのが強みです。

# COMMAND ----------

# DBTITLE 1,ライブラリインストール
# MAGIC %pip install "psycopg[binary]>=3.1" openai --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Lakebase プロジェクトの確認・作成
# ==============================================================
# Lakebase プロジェクトの確認（なければ自動作成）
# ==============================================================
# REST API 経由で操作（databricks-sdk バージョン差を吸収するため
# api_client.do を直接使用。CLI の `databricks postgres ...` と等価）
from databricks.sdk import WorkspaceClient
import time

w = WorkspaceClient()

def pg_api(method, path, body=None, query=None):
    """Lakebase (postgres) REST API 呼び出しヘルパー"""
    return w.api_client.do(method, f"/api/2.0/postgres{path}", body=body, query=query)

# --- プロジェクト存在確認 ---
project_exists = False
try:
    proj = pg_api("GET", f"/projects/{LAKEBASE_PROJECT_ID}")
    project_exists = True
    print(f"✅ 既存 Lakebase プロジェクトを再利用: {LAKEBASE_PROJECT_ID}")
except Exception as e:
    if "404" in str(e) or "NOT_FOUND" in str(e).upper():
        print(f"プロジェクト {LAKEBASE_PROJECT_ID} は存在しません → 作成します")
    else:
        raise

# --- なければ作成（production ブランチ + primary エンドポイントが自動付帯）---
if not project_exists:
    resp = pg_api(
        "POST", "/projects",
        body={"spec": {"display_name": "Manufacturing Doc Search Hands-on"}},
        query={"project_id": LAKEBASE_PROJECT_ID},
    )
    op_name = resp.get("name", "")
    print(f"🚀 プロジェクト作成中... (operation: {op_name})")
    start = time.time()
    while time.time() - start < 600:
        op = pg_api("GET", f"/{op_name}") if op_name else {"done": True}
        if op.get("done", False):
            break
        time.sleep(10)
    print(f"✅ プロジェクト作成完了: {LAKEBASE_PROJECT_ID}")

# COMMAND ----------

# DBTITLE 1,接続ヘルパー定義
# ==============================================================
# Lakebase への psycopg 接続ヘルパー
# ==============================================================
# 認証: OAuth トークン（1時間で失効）をパスワードとして使用。
# 長時間セッションでは get_conn() を都度呼んでトークンを再取得する。
import psycopg

def get_lakebase_host():
    ep = pg_api("GET", f"/{LAKEBASE_ENDPOINT_PATH}")
    return ep["status"]["hosts"]["host"]

def get_lakebase_token():
    cred = pg_api("POST", "/credentials", body={"endpoint": LAKEBASE_ENDPOINT_PATH})
    return cred["token"]

def get_conn():
    """Lakebase への新規接続を返す（呼ぶたびにトークン再取得）"""
    return psycopg.connect(
        host=get_lakebase_host(),
        dbname=LAKEBASE_PG_DATABASE,
        user=w.current_user.me().user_name,
        password=get_lakebase_token(),
        sslmode="require",
        autocommit=True,
    )

# 疎通確認（プロジェクト作成直後はエンドポイント起動待ちのためリトライ）
last_err = None
for attempt in range(12):
    try:
        with get_conn() as conn:
            ver = conn.execute("SELECT version()").fetchone()[0]
        last_err = None
        break
    except Exception as e:
        last_err = e
        print(f"   接続待機中... ({attempt+1}/12)")
        time.sleep(15)
if last_err:
    raise last_err

print(f"✅ Lakebase 接続成功: {LAKEBASE_ENDPOINT_PATH}")
print(f"   host: {get_lakebase_host()}")
print(f"   {ver[:60]}...")

# COMMAND ----------

# DBTITLE 1,Lakebase Search / pgvector 拡張のセットアップ
# ==============================================================
# 検索拡張のセットアップ（利用可否を自動判定）
# ==============================================================
# Lakebase Search (lakebase_vector / lakebase_text) が有効ならそれを使い、
# 無効なら標準 pgvector (vector + hnsw) にフォールバックする。
LAKEBASE_SEARCH_VECTOR = False  # lakebase_vector が使えるか
LAKEBASE_SEARCH_TEXT = False    # lakebase_text (BM25) が使えるか

with get_conn() as conn:
    # --- ベクトル拡張 ---
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE")
        LAKEBASE_SEARCH_VECTOR = True
        print("✅ lakebase_vector 拡張: 有効 (Lakebase Search)")
    except Exception as e:
        print(f"ℹ️ lakebase_vector は利用不可 → 標準 pgvector にフォールバック")
        print(f"   ({str(e).splitlines()[0] if str(e) else e})")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- BM25 全文検索拡張（任意）---
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS lakebase_text")
        LAKEBASE_SEARCH_TEXT = True
        print("✅ lakebase_text 拡張: 有効 (BM25 全文検索)")
    except Exception:
        print("ℹ️ lakebase_text は利用不可（06b のハイブリッド検索は標準 ts_rank を使用）")

if not (LAKEBASE_SEARCH_VECTOR or LAKEBASE_SEARCH_TEXT):
    print()
    print("💡 Lakebase Search を有効にするには:")
    print("   ワークスペース UI → Lakebase → プロジェクト選択")
    print("   → Settings → Lakebase Search → Enable")
    print("   （有効化は不可逆・コンピュートが再起動されます）")
    print("   有効化後にこのセル以降を再実行してください。")

# COMMAND ----------

# DBTITLE 1,検索テーブル作成
# ==============================================================
# pgvector スキーマ・テーブル作成
# ==============================================================
# 05 (Vector Search) の「Delta Sync インデックス」に相当するものを
# 自分で DDL として定義するのが Lakebase パターンの特徴。
# content_tsv: BM25 / 全文検索用の tsvector 生成列。
# 'simple' 辞書はステミングを行わないため、日本語混じり文や
# 製品ID (SNS-100 等) のトークンをそのまま保持できる。
with get_conn() as conn:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {LAKEBASE_PG_SCHEMA}")
    # ハンズオンのやり直しに対応するため DROP & CREATE
    conn.execute(f"DROP TABLE IF EXISTS {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")
    conn.execute(f"""
        CREATE TABLE {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS} (
            chunk_id        BIGINT PRIMARY KEY,
            doc_id          TEXT NOT NULL,
            content         TEXT NOT NULL,
            product_ids_str TEXT,
            doc_type        TEXT,
            file_path       TEXT,
            embedding       VECTOR({EMBEDDING_DIM}),
            content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
        )
    """)

print(f"✅ テーブル作成: {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")
print(f"   埋め込み次元: {EMBEDDING_DIM} ({EMBEDDING_ENDPOINT})")

# COMMAND ----------

# DBTITLE 1,doc_chunks のロードと埋め込み付与
# ==============================================================
# doc_chunks を読み込み → 埋め込み生成 → Lakebase に INSERT
# ==============================================================
# Vector Search の「マネージドエンベディング」相当を自分で行う。
# Foundation Model API (OpenAI 互換) でチャンク本文をベクトル化する。
import openai

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
client = openai.OpenAI(
    api_key=ctx.apiToken().get(),
    base_url=f"{ctx.apiUrl().get()}/serving-endpoints",
)

def embed_texts(texts, batch_size=32):
    """テキスト列を埋め込みベクトル列に変換"""
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embeddings.create(model=EMBEDDING_ENDPOINT, input=batch)
        # input と同じ順序で返るよう index でソート
        vectors.extend([d.embedding for d in sorted(resp.data, key=lambda d: d.index)])
    return vectors

# UC の doc_chunks を取得
chunks = spark.sql(f"""
    SELECT chunk_id, doc_id, content, product_ids_str, doc_type, file_path
    FROM {FQ_DOC_CHUNKS} ORDER BY chunk_id
""").collect()
print(f"ロード対象: {len(chunks)} チャンク")

# 埋め込み生成
print(f"埋め込み生成中... ({EMBEDDING_ENDPOINT})")
t0 = time.time()
embeddings = embed_texts([c.content for c in chunks])
print(f"  完了: {len(embeddings)} 件 ({time.time()-t0:.1f}秒)")

# Lakebase に INSERT（pgvector には '[v1,v2,...]' 文字列として渡す）
rows = [
    (c.chunk_id, c.doc_id, c.content, c.product_ids_str, c.doc_type, c.file_path,
     "[" + ",".join(f"{v:.6f}" for v in vec) + "]")
    for c, vec in zip(chunks, embeddings)
]
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
                (chunk_id, doc_id, content, product_ids_str, doc_type, file_path, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector)""",
            rows,
        )
print(f"✅ Lakebase ロード完了: {len(rows)} 行")

# COMMAND ----------

# DBTITLE 1,ANN / BM25 インデックス作成
# ==============================================================
# 検索インデックス作成
# ==============================================================
# Vector Search が内部でやってくれるインデックス管理を、
# Lakebase では自分で選べる（lakebase_ann / HNSW / IVFFlat）。
with get_conn() as conn:
    if LAKEBASE_SEARCH_VECTOR:
        # Lakebase Search の ANN インデックス（大規模・スケールトゥーゼロ対応）
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{LAKEBASE_TABLE_CHUNKS}_ann
            ON {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            USING lakebase_ann (embedding vector_cosine_ops)
        """)
        print("✅ lakebase_ann インデックス作成 (Lakebase Search)")
    else:
        # 標準 pgvector の HNSW インデックス
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{LAKEBASE_TABLE_CHUNKS}_hnsw
            ON {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            USING hnsw (embedding vector_cosine_ops)
        """)
        print("✅ HNSW インデックス作成 (pgvector)")

    if LAKEBASE_SEARCH_TEXT:
        # BM25 全文検索インデックス（06b のハイブリッド検索で使用）
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{LAKEBASE_TABLE_CHUNKS}_bm25
            ON {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            USING lakebase_bm25 (content_tsv)
        """)
        print("✅ lakebase_bm25 インデックス作成 (BM25 全文検索)")

    # メタデータ検索用の通常インデックスも併設
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{LAKEBASE_TABLE_CHUNKS}_doc
        ON {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS} (doc_id)
    """)
    conn.execute(f"ANALYZE {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")

print("✅ インデックス作成完了")

# COMMAND ----------

# DBTITLE 1,検証: テストクエリ
# ==============================================================
# 検証: ベクトル類似検索の動作確認
# ==============================================================
# 05 の query_index に相当: 質問をベクトル化し、
# <=> (コサイン距離) で近い順に取得
question = "SNS-100 の動作温度範囲"
qvec = embed_texts([question])[0]
qvec_str = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"

with get_conn() as conn:
    hits = conn.execute(
        f"""SELECT chunk_id, doc_id, product_ids_str, doc_type,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
            ORDER BY embedding <=> %s::vector
            LIMIT 3""",
        (qvec_str, qvec_str),
    ).fetchall()

print(f"テストクエリ: '{question}'")
print(f"  ヒット数: {len(hits)}")
for h in hits:
    print(f"  - chunk_id={h[0]}, doc={h[1]}, products={h[2]}, type={h[3]}, sim={h[4]:.3f}")

assert len(hits) >= 1, "検索結果が 0 件です"
print(f"\n✅ 05b_lakebase_index 完了: Lakebase 上でセマンティック検索が可能です")
print("→ 次の 06b_rag_query_lakebase ノートブックで RAG 検索を体験しましょう！")
