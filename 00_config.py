# Databricks notebook source
# DBTITLE 1,設定ファイル: 全ノートブック共通設定
# MAGIC %md
# MAGIC # 00_config: 全ノートブック共通設定
# MAGIC
# MAGIC ## 目的
# MAGIC このノートブックは、ハンズオン教材全体で使用する設定値を一箇所で管理します。
# MAGIC
# MAGIC ## 使い方
# MAGIC - **Databricks Free Edition**: そのまま実行してください（変更不要）
# MAGIC - **有償ワークスペース**: 下記の `CATALOG` と `SCHEMA` を環境に合わせて変更してください
# MAGIC
# MAGIC ## 重要
# MAGIC **すべてのノートブックは先頭で `%run ./00_config` を実行してこのファイルを読み込みます。**
# MAGIC カタログ名・スキーマ名のハードコードは禁止です。

# COMMAND ----------

# DBTITLE 1,Unity Catalog 設定
# Databricks notebook source
# ==============================================================
# Unity Catalog 設定
# ==============================================================
# Free Edition: そのまま使用（workspace カタログは最初から存在）
# 有償ワークスペース: 以下を書き換え (例: CATALOG = "main")
CATALOG = "workspace"  # Free Edition ではこのまま使用
SCHEMA = "mfg_doc_search"
VOLUME = "docs"

# ==============================================================
# パス設定（Volume 内のディレクトリ構造）
# ==============================================================
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
RAW_DIR = f"{VOLUME_PATH}/raw"
IMAGES_DIR = f"{VOLUME_PATH}/images"
WAVEFORMS_DIR = f"{VOLUME_PATH}/waveforms"
THUMBS_DIR = f"{VOLUME_PATH}/thumbnails"

# COMMAND ----------

# DBTITLE 1,テーブル名設定
# ==============================================================
# テーブル名
# ==============================================================
TABLE_DOCUMENTS = "documents"
TABLE_MEDIA_ASSETS = "media_assets"
TABLE_EXCEL_CELLS = "excel_cells"
TABLE_DOC_CHUNKS = "doc_chunks"

# 完全修飾テーブル名（SQLやSparkで使用）
FQ_DOCUMENTS = f"{CATALOG}.{SCHEMA}.{TABLE_DOCUMENTS}"
FQ_MEDIA_ASSETS = f"{CATALOG}.{SCHEMA}.{TABLE_MEDIA_ASSETS}"
FQ_EXCEL_CELLS = f"{CATALOG}.{SCHEMA}.{TABLE_EXCEL_CELLS}"
FQ_DOC_CHUNKS = f"{CATALOG}.{SCHEMA}.{TABLE_DOC_CHUNKS}"

# COMMAND ----------

# DBTITLE 1,Model Serving / Vector Search 設定
# ==============================================================
# Model Serving エンドポイント
# ==============================================================
# 埋め込みモデル: pay-per-token の基盤モデルを使用
# Free Edition では databricks-gte-large-en が利用可能（英語系）
# 日本語対応が必要な場合: databricks-bge-large-en も候補
EMBEDDING_ENDPOINT = "databricks-gte-large-en"

# LLM: 回答生成用の基盤モデル
LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

# ==============================================================
# Vector Search 設定
# ==============================================================
# Free Edition ではアカウントに 1 エンドポイント・1 ユニットまで
# 既存エンドポイントがあれば再利用するロジックを 05 ノートブックに実装
VS_ENDPOINT_NAME = "mfg_handson_vs"
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.{TABLE_DOC_CHUNKS}_index"

# COMMAND ----------

# DBTITLE 1,代替検索バックエンド設定（有償ワークスペース向け）
# ==============================================================
# 代替検索バックエンド（AI Search 以外のパターン）
# ==============================================================
# 検索バックエンドの切り替え:
#   "vector_search"      : 05/06 ノートブック（Vector Search — オリジナル）
#   "lakebase"           : 05b/06b ノートブック（Lakebase pgvector）
#   "lakebase_agent_mem" : 06c ノートブック（Lakebase + Agent Memory）
#   "genie_content"      : 07b ノートブック（Genie + content search）
#
# ※ Lakebase / Agent Memory / Genie content search は
#   有償ワークスペースが前提です（Free Edition では動作しません）。
SEARCH_MODE = "lakebase"

# ==============================================================
# Lakebase 設定（05b / 06b / 06c で使用）
# ==============================================================
# Lakebase Autoscaling プロジェクト（なければ 05b が自動作成）
LAKEBASE_PROJECT_ID = "mfg-handson-lakebase"
LAKEBASE_BRANCH_ID = "production"
LAKEBASE_ENDPOINT_ID = "primary"
LAKEBASE_PG_DATABASE = "databricks_postgres"

# Postgres 側のスキーマ・テーブル名（[A-Za-z0-9_] のみ使用可）
LAKEBASE_PG_SCHEMA = "mfg_search"
LAKEBASE_TABLE_CHUNKS = "doc_chunks"
LAKEBASE_TABLE_MEMORY = "agent_memory"

# 埋め込みベクトル次元数（databricks-gte-large-en / bge-large-en は 1024）
EMBEDDING_DIM = 1024

# Lakebase リソースパス（REST API 用）
LAKEBASE_BRANCH_PATH = f"projects/{LAKEBASE_PROJECT_ID}/branches/{LAKEBASE_BRANCH_ID}"
LAKEBASE_ENDPOINT_PATH = f"{LAKEBASE_BRANCH_PATH}/endpoints/{LAKEBASE_ENDPOINT_ID}"

# ==============================================================
# Agent Memory 設定（06c で使用）
# ==============================================================
# UC メモリストア名（CATALOG.SCHEMA 配下に作成される UC セキュアブル）
MEMORY_STORE_NAME = "mfg_agent_memory"
MEMORY_STORE_FULL_NAME = f"{CATALOG}.{SCHEMA}.{MEMORY_STORE_NAME}"

# エージェントが使うモデル（Responses API 対応モデル）
# ワークスペースで利用可能なものに変更してください
AGENT_MODEL = "databricks-gpt-5-2"

# COMMAND ----------

# DBTITLE 1,機能フラグ
# ==============================================================
# 機能フラグ
# ==============================================================
# True: ai_query / LLM を使ってキーワード抽出・要約を実行
# False: ルールベース（正規表現+固定辞書）で代替
USE_AI_FUNCTIONS = True

# ==============================================================
# Free Edition 高速化モード
# ==============================================================
# True: デモ質問に必要な最小限のドキュメントだけチャンク化
#       → インデックス作成が約 3–5分で完了
# False: 全ドキュメントをチャンク化（通常ワークスペース向け）
LITE_MODE = True

# COMMAND ----------

# DBTITLE 1,設定値一覧表示
# ==============================================================
# 設定値の確認表示
# ==============================================================
print("=" * 60)
print("製造業向けドキュメント検索 RAG ハンズオン - 設定値")
print("=" * 60)
print(f"  CATALOG:            {CATALOG}")
print(f"  SCHEMA:             {SCHEMA}")
print(f"  VOLUME:             {VOLUME}")
print(f"  VOLUME_PATH:        {VOLUME_PATH}")
print(f"  RAW_DIR:            {RAW_DIR}")
print(f"  IMAGES_DIR:         {IMAGES_DIR}")
print(f"  WAVEFORMS_DIR:      {WAVEFORMS_DIR}")
print(f"  THUMBS_DIR:         {THUMBS_DIR}")
print(f"  ---")
print(f"  TABLE_DOCUMENTS:    {FQ_DOCUMENTS}")
print(f"  TABLE_MEDIA_ASSETS: {FQ_MEDIA_ASSETS}")
print(f"  TABLE_EXCEL_CELLS:  {FQ_EXCEL_CELLS}")
print(f"  TABLE_DOC_CHUNKS:   {FQ_DOC_CHUNKS}")
print(f"  ---")
print(f"  EMBEDDING_ENDPOINT: {EMBEDDING_ENDPOINT}")
print(f"  LLM_ENDPOINT:       {LLM_ENDPOINT}")
print(f"  VS_ENDPOINT_NAME:   {VS_ENDPOINT_NAME}")
print(f"  VS_INDEX_NAME:      {VS_INDEX_NAME}")
print(f"  ---")
print(f"  SEARCH_MODE:        {SEARCH_MODE}")
print(f"  LAKEBASE_PROJECT:   {LAKEBASE_PROJECT_ID}")
print(f"  LAKEBASE_ENDPOINT:  {LAKEBASE_ENDPOINT_PATH}")
print(f"  LAKEBASE_PG_TABLE:  {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")
print(f"  EMBEDDING_DIM:      {EMBEDDING_DIM}")
print(f"  ---")
print(f"  USE_AI_FUNCTIONS:   {USE_AI_FUNCTIONS}")
print(f"  LITE_MODE:          {LITE_MODE}")
print("=" * 60)
print("✅ 設定読み込み完了")
