# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,07b Genie content search: 紹介
# MAGIC %md
# MAGIC # 07b_genie_content_search: Genie Agent + content search でドキュメント探索
# MAGIC
# MAGIC ## 目的
# MAGIC - **第3のパターン**: RAG を自前構築せず、**Genie Agent の content search** に
# MAGIC   ドキュメント検索を任せる
# MAGIC - Genie Agent に UC ボリュームをアタッチすると、
# MAGIC   PDF / Word / PPT / TIFF 等のファイルを直接読んで回答できる（Beta）
# MAGIC
# MAGIC ## 所要時間目安: 10分
# MAGIC
# MAGIC ## 前提
# MAGIC - **有償ワークスペース**
# MAGIC - 01〜03 ノートブック実行済み（Volume に生ファイルが配置済み）
# MAGIC - ワークスペース管理者がプレビュー **「Analyze Files in Volumes with Genie Agents」** を有効化済み
# MAGIC
# MAGIC ## 06/06b/06c との違い
# MAGIC | 観点 | 06系 (自前 RAG) | 07b (Genie + content search) |
# MAGIC |---|---|---|
# MAGIC | 構築 | チャンク化・埋め込み・検索を実装 | UI でボリュームをアタッチするだけ |
# MAGIC | 前処理 | テキスト抽出パイプライン (02/03) が前提 | 生ファイルを直接読む（抽出不要） |
# MAGIC | 構造化データの集計 | 別途 SQL が必要 | テーブルも同じ Agent で扱える |
# MAGIC | カスタマイズ性 | 高い（検索ロジック自在） | プラットフォーム任せ |
# MAGIC
# MAGIC ## 製造業における位置づけ
# MAGIC 「まず Genie に読ませて十分か」を検証し、精度・権限・表示制御の要件が
# MAGIC 高い場合に 06系の自前 RAG に進む——という段階的導入の第一歩として有効です。

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,前提確認: Volume の生ファイル
# ==============================================================
# 前提確認: Genie にアタッチする Volume の中身
# ==============================================================
# Genie Agent はボリューム単位でアタッチする（フォルダ単位ではない）。
# このハンズオンでは docs ボリューム全体を対象にする。
import os

for subdir, label in [(RAW_DIR, "生ドキュメント"), (IMAGES_DIR, "抽出画像"), (WAVEFORMS_DIR, "波形CSV")]:
    if os.path.exists(subdir):
        files = os.listdir(subdir)
        print(f"✅ {label}: {subdir} ({len(files)} ファイル)")
        for f in files[:5]:
            print(f"     ・{f}")
    else:
        print(f"⚠️ {label} ディレクトリがありません: {subdir}")
        print("   → 01〜03 ノートブックを先に実行してください")

# COMMAND ----------

# DBTITLE 1,Genie スペースの確認・作成
# ==============================================================
# Genie スペース（Genie Agent）の確認・作成
# ==============================================================
# 構造化テーブル (documents / media_assets / excel_cells) をデータソースに持つ
# スペースを用意し、そこに後述の UI 手順でボリュームをアタッチする。
from databricks.sdk import WorkspaceClient
import json

w = WorkspaceClient()

GENIE_SPACE_NAME = "製造ドキュメント検索 - content search ハンズオン"

# 既存スペースを検索
genie_space_id = None
for space in (w.genie.list_spaces().spaces or []):
    if space.title == GENIE_SPACE_NAME:
        genie_space_id = space.space_id
        break

if genie_space_id:
    print(f"✅ 既存 Genie スペースを再利用: {GENIE_SPACE_NAME}")
    print(f"   Space ID: {genie_space_id}")
else:
    # --- 新規作成 ---
    # ウェアハウスを自動選択
    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError("SQL ウェアハウスがありません。先に作成してください。")
    warehouse_id = warehouses[0].id
    print(f"使用ウェアハウス: {warehouses[0].name} ({warehouse_id})")

    # 親フォルダを確保
    me = w.current_user.me().user_name
    parent_path = f"/Workspace/Users/{me}/genie_spaces"
    try:
        w.workspace.mkdirs(parent_path)
    except Exception:
        pass

    serialized_space = {
        "version": 2,
        "data_sources": {
            "tables": [
                {"identifier": FQ_DOCUMENTS},
                {"identifier": FQ_MEDIA_ASSETS},
                {"identifier": FQ_EXCEL_CELLS},
            ]
        },
        "config": {
            "sample_questions": [
                {"id": "10000000000000000000000000000001",
                 "question": ["製品ごとのドキュメント数を教えて"]},
                {"id": "10000000000000000000000000000002",
                 "question": ["SNS-200 の過渡応答の試験結果を教えて"]},
                {"id": "10000000000000000000000000000003",
                 "question": ["取り消し線で修正された測定値があるファイルはどれ？"]},
            ]
        },
        "instructions": {
            "text_instructions": [
                {"id": "30000000000000000000000000000001",
                 "content": [
                     "製造業の技術ドキュメント（試験成績書・仕様書・データシート）を扱うスペースです。\n",
                     "製品の仕様・試験結果・ドキュメント内容に関する質問には、アタッチされたボリューム内のファイルを参照して回答してください。\n",
                     "件数の集計や一覧の質問にはテーブル (documents / media_assets / excel_cells) を使ってください。\n",
                     "回答は日本語で、根拠となったファイル名を明記してください。",
                 ]}
            ]
        },
    }

    resp = w.api_client.do("POST", "/api/2.0/genie/spaces", body={
        "warehouse_id": warehouse_id,
        "title": GENIE_SPACE_NAME,
        "description": "製造業ドキュメント検索ハンズオン: テーブル + ボリューム content search",
        "parent_path": parent_path,
        "serialized_space": json.dumps(serialized_space, ensure_ascii=False),
    })
    genie_space_id = resp.get("space_id") or resp.get("id")
    print(f"✅ Genie スペース作成: {GENIE_SPACE_NAME}")
    print(f"   Space ID: {genie_space_id}")

workspace_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
print(f"\nアクセス URL:")
print(f"  {workspace_url}/genie/rooms/{genie_space_id}")

# COMMAND ----------

# DBTITLE 1,アタッチ対象のボリューム情報
# ==============================================================
# 次の手動ステップで使う値を表示
# ==============================================================
print("=" * 60)
print("次のセルの手順で UI から設定する値:")
print("=" * 60)
print(f"  Genie スペース URL:")
print(f"    {workspace_url}/genie/rooms/{genie_space_id}")
print(f"  アタッチするボリューム:")
print(f"    {CATALOG} / {SCHEMA} / {VOLUME}   ({VOLUME_PATH})")
print("=" * 60)

# COMMAND ----------

# DBTITLE 1,【手動ステップ】ボリュームのアタッチと content search 有効化
# MAGIC %md
# MAGIC ## 【手動ステップ】ボリュームのアタッチと content search 有効化
# MAGIC
# MAGIC ボリュームのアタッチは **現時点では UI 操作のみ** です（Beta）。
# MAGIC 上のセルに表示した URL からスペースを開き、以下を実施してください:
# MAGIC
# MAGIC ### 1. ボリュームをアタッチ
# MAGIC 1. Genie スペースの **Sources（ソース）** タブを開く
# MAGIC 2. **Add（追加）** → **Volume（ボリューム）** を選択
# MAGIC 3. 上のセルに表示したボリューム（`docs`）を選択
# MAGIC 4. 説明（Description）に「製造業の技術ドキュメント一式（試験成績書・仕様書・データシート）」等と記入
# MAGIC
# MAGIC ### 2. content search を有効化
# MAGIC - ボリューム追加時の **content search** トグルを **ON**
# MAGIC - 有効にすると、ファイルが事前にインデックス化され、
# MAGIC   質問時の解析ではなくインデックス検索で高速に回答できるようになります
# MAGIC   （最大 10,000 ファイル / 50MB まで対応）
# MAGIC
# MAGIC ### 対応ファイル形式
# MAGIC PDF / JPG / PNG / TIFF / DOC / DOCX / PPT / PPTX
# MAGIC
# MAGIC ### 前提（管理者向け）
# MAGIC ワークスペースのプレビュー設定で
# MAGIC **「Analyze Files in Volumes with Genie Agents」** が有効である必要があります。
# MAGIC
# MAGIC ---
# MAGIC **完了したら次のセルに進んでください。**

# COMMAND ----------

# DBTITLE 1,デモ: Genie に質問（Conversation API）
# ==============================================================
# デモ: Genie Agent への質問（Conversation API 経由）
# ==============================================================
# ボリュームをアタッチ済みなら、ドキュメントの中身に関する質問に
# Genie が直接回答する。自前 RAG (06系) と回答を比較してみよう。
import time

def ask_genie(question, conversation_id=None, timeout_sec=180):
    """Genie に質問して回答テキストと生成SQLを返す"""
    if conversation_id is None:
        resp = w.api_client.do(
            "POST", f"/api/2.0/genie/spaces/{genie_space_id}/start-conversation",
            body={"content": question})
    else:
        resp = w.api_client.do(
            "POST", f"/api/2.0/genie/spaces/{genie_space_id}/conversations/{conversation_id}/messages",
            body={"content": question})
    # 応答形式: {"message_id": ..., "message": {"id": ..., "conversation_id": ...}}
    conv_id = (resp.get("conversation_id")
               or (resp.get("message") or {}).get("conversation_id")
               or conversation_id)
    msg = resp.get("message") or resp
    msg_id = resp.get("message_id") or msg.get("id")

    # 完了をポーリング
    start = time.time()
    while time.time() - start < timeout_sec:
        m = w.api_client.do(
            "GET",
            f"/api/2.0/genie/spaces/{genie_space_id}/conversations/{conv_id}/messages/{msg_id}")
        status = m.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(5)

    texts, sqls = [], []
    for att in (m.get("attachments") or []):
        if att.get("text"):
            texts.append(att["text"].get("content", ""))
        if att.get("query"):
            sqls.append(att["query"].get("query", ""))
    if m.get("error"):
        texts.append(f"⚠️ エラー: {m['error']}")
    return conv_id, "\n".join(texts), sqls

# --- 構造化データの質問（テーブルを使う）---
q1 = "製品ごとのドキュメント数を教えて"
print(f"{'='*60}\n🧑 質問: {q1}\n{'='*60}")
conv_id, text, sqls = ask_genie(q1)
print(f"\n🤖 回答:\n{text}")
if sqls:
    print(f"\n生成SQL:\n{sqls[0]}")

# --- ドキュメント内容の質問（ボリュームの content search を使う）---
# ※ ボリューム未アタッチの場合は「分からない」系の回答になります
q2 = "SNS-200 の過渡応答の試験結果を教えて"
print(f"\n{'='*60}\n🧑 質問: {q2}\n{'='*60}")
conv_id, text, sqls = ask_genie(q2, conversation_id=conv_id)
print(f"\n🤖 回答:\n{text}")

q3 = "取り消し線で修正された測定値があるファイルはどれ？"
print(f"\n{'='*60}\n🧑 質問: {q3}\n{'='*60}")
conv_id, text, sqls = ask_genie(q3, conversation_id=conv_id)
print(f"\n🤖 回答:\n{text}")

# COMMAND ----------

# DBTITLE 1,まとめ
# MAGIC %md
# MAGIC ## Genie + content search パターンのまとめ
# MAGIC
# MAGIC ### このパターンが向いているケース
# MAGIC - まずノーコードで「ドキュメントに答えられるか」を検証したい
# MAGIC - 構造化データの集計とドキュメント参照を **1つの窓口** にしたい
# MAGIC - 権限は質問したユーザー本人のものが適用される（UC 権限そのまま）
# MAGIC
# MAGIC ### 自前 RAG (06/06b/06c) が向いているケース
# MAGIC - 検索ロジック（チャンク設計・ハイブリッド・フィルタ）を制御したい
# MAGIC - 図・波形の自動表示など、回答のレンダリングを作り込みたい
# MAGIC - アプリ/エージェントへの組み込み（API として使いたい）
# MAGIC
# MAGIC ### 制限メモ（Beta 時点）
# MAGIC - ボリュームのアタッチは UI のみ（API 未公開）
# MAGIC - ボリューム単位でのアタッチ（最大 10 ボリューム）
# MAGIC - content search 利用時: 最大 10,000 ファイル / 50MB まで
# MAGIC - インデックス化に ingest + クエリのコストが発生
