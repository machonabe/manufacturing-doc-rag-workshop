# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,06 RAGクエリ: ゴール体験
# MAGIC %md
# MAGIC # 06_rag_query: 自然言語検索 → 仕様・図・波形の即時表示
# MAGIC
# MAGIC ## 目的
# MAGIC **このノートブックがハンズオンのゴール体験です。**
# MAGIC
# MAGIC 自然言語で問い合わせると、関連する仕様書・ブロック図・波形データが即座に表示されます。
# MAGIC
# MAGIC ## 所要時間目安: 15分
# MAGIC
# MAGIC ## 前提
# MAGIC - 05 ノートブックが実行済み（Vector Search インデックスが READY）
# MAGIC
# MAGIC ## 学びの意義
# MAGIC Knowledge Assistant（Agent Bricks）は Free Edition では利用できません。
# MAGIC だからこそ、Vector Search + LLM で RAG を自前構築する——その仵組みを理解することに価値があります。

# COMMAND ----------

# DBTITLE 1,ライブラリ・設定
# MAGIC %pip install openai --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,RAG検索関数の定義
# ==============================================================
# RAG 検索関数: 自然言語 → 検索 → 回答 → 図・波形表示
# ==============================================================
from databricks.sdk import WorkspaceClient
import openai, os, re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image as PILImage
import csv as csv_mod
import numpy as np

w = WorkspaceClient()

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

def answer(question: str, num_results: int = 5):
    """
    自然言語で問い合わせると、関連する仕様・図・波形が即座に表示される。
    
    製造業実務: 設計・品質エンジニアが「あの試験結果は？」「この製品の仕様は？」と
    聞いたら、関連資料がまとめて表示される——そんな体験です。
    """
    print(f"\n{'='*60}")
    print(f"🔍 質問: {question}")
    print(f"{'='*60}")
    
    # --- Step 1: Vector Search (databricks-sdk 使用) ---
    try:
        results = w.vector_search_indexes.query_index(
            index_name=VS_INDEX_NAME,
            columns=["chunk_id", "doc_id", "content", "product_ids_str", "file_path"],
            query_text=question,
            num_results=num_results
        )
        hits = results.result.data_array
        print(f"\n📚 検索ヒット: {len(hits)} 件")
    except Exception as e:
        print(f"\n⚠️ Vector Search エラー: {e}")
        print("→ インデックスがまだ READY でない可能性があります。数分待って再実行してください。")
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
            # OpenAI互換 APIで pay-per-token LLMを呼び出し
            client = openai.OpenAI(
                api_key=dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get(),
                base_url=f"{dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()}/serving-endpoints"
            )
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
                # ガードレールの誤検知（製造業用語が暴力カテゴリとして誤判定される既知の問題）
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
