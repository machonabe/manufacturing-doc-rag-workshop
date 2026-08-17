# Databricks notebook source
# DBTITLE 1,07 Genie Space: 紹介
# MAGIC %md
# MAGIC # 07_genie_space: 自然言語 SQL 探索
# MAGIC
# MAGIC ## 目的
# MAGIC - 抽出したメタデータを Genie Space で自然言語探索可能にする
# MAGIC - 「どの製品の試験が一番多い？」「取り消し線があるファイルは？」といった構造化クエリを体験
# MAGIC
# MAGIC ## 所要時間目安: 5分
# MAGIC
# MAGIC ## 前提
# MAGIC - 02〜04 ノートブックが実行済み（テーブルが存在）
# MAGIC
# MAGIC ## 06 との使い分け
# MAGIC - **06 (RAG)**: 非構造化テキストをセマンティック検索→LLM回答生成
# MAGIC - **07 (Genie)**: 構造化メタデータを SQL で集計・分析
# MAGIC
# MAGIC 両方を組み合わせることで、「ドキュメントの中身を読む」と「データを集計する」の両方をカバーできます。

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Genie Space 確認
# ==============================================================
# Genie Space の確認とアクセス
# ==============================================================
# Genie Space は自然言語で SQL テーブルを探索できるツールです。
# 製造業実務: 品質管理部門が「今月の試験 NG 件数は？」と聞くような場面で活用。
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

GENIE_SPACE_NAME = "製造ドキュメント検索 - ハンズオン"

# 既存の Space を検索
genie_space_id = None
existing_spaces = w.genie.list_spaces().spaces or []
for space in existing_spaces:
    if space.title == GENIE_SPACE_NAME:
        genie_space_id = space.space_id
        break

if genie_space_id:
    print(f"✅ Genie Space 確認: {GENIE_SPACE_NAME}")
    print(f"   Space ID: {genie_space_id}")
else:
    print(f"⚠️ Genie Space '{GENIE_SPACE_NAME}' が見つかりません")
    print("   → ワークスペース UI から作成してください:")
    print(f"   1. 左サイドバー→ Genie → New")
    print(f"   2. タイトル: {GENIE_SPACE_NAME}")
    print(f"   3. テーブル追加: {FQ_DOCUMENTS}, {FQ_MEDIA_ASSETS}, {FQ_EXCEL_CELLS}")
    # フォールバック: デモクエリのみ実行
    genie_space_id = "PENDING"

workspace_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
if genie_space_id and genie_space_id != "PENDING":
    print(f"\nアクセス URL:")
    print(f"  {workspace_url}/genie/rooms/{genie_space_id}")

# COMMAND ----------

# DBTITLE 1,デモ: SQL クエリ例
# ==============================================================
# デモ: Genie Space で聞けるような質問を SQL で体験
# ==============================================================
print("▶ 質問例 1: 製品ごとのドキュメント数は？")
display(spark.sql(f"""
    SELECT product_id, doc_type, COUNT(*) as doc_count
    FROM (
        SELECT EXPLODE(product_ids) as product_id, doc_type
        FROM {FQ_DOCUMENTS}
    )
    GROUP BY product_id, doc_type
    ORDER BY product_id, doc_type
"""))

print("\n\u25b6 質問例 2: 取り消し線があるファイルは？")
display(spark.sql(f"""
    SELECT file_name, sheet, cell, value
    FROM {FQ_EXCEL_CELLS}
    WHERE is_strikethrough = true
    ORDER BY file_name, sheet, cell
"""))

print("\n\u25b6 質問例 3: ブロック図がある製品は？")
display(spark.sql(f"""
    SELECT product_id, description, file_path
    FROM {FQ_MEDIA_ASSETS}
    WHERE asset_type = 'block_diagram'
    ORDER BY product_id
"""))

# COMMAND ----------

# DBTITLE 1,検証
# ==============================================================
# 検証
# ==============================================================
assert genie_space_id is not None, "Genie Space ID が取得できませんでした"

print("✅ 07_genie_space 完了")
print(f"\nハンズオン全体の完了おめでとうございます！")
print("\nこのハンズオンで学んだこと:")
print("  1. 非構造化ドキュメントからのメタデータ抽出")
print("  2. Vector Search を使ったセマンティック検索")
print("  3. RAG による自然言語 Q&A")
print("  4. Genie Space による構造化データ探索")
print("\n次のステップ:")
print("  - Knowledge Assistant でのエージェント化（有償ワークスペース）")
print("  - 実データでの適用（Box MCP / SharePoint 経由取り込み）")
