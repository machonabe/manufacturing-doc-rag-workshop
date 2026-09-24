# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,99b 代替パターンのクリーンアップ
# MAGIC %md
# MAGIC # 99b_cleanup_alt: 代替パターンのリソース削除
# MAGIC
# MAGIC ## 目的
# MAGIC 05b / 06b / 06c / 07b で作成したリソースを削除します。
# MAGIC
# MAGIC ## 対象リソース
# MAGIC | リソース | 作成ノートブック | 削除のデフォルト |
# MAGIC |---|---|---|
# MAGIC | Lakebase 検索テーブル (`mfg_search.doc_chunks`) | 05b | 削除 |
# MAGIC | UC メモリストア (`mfg_agent_memory`) | 06c | 削除 |
# MAGIC | Genie スペース | 07b | 削除 |
# MAGIC | Lakebase プロジェクト全体 | 05b | **残す**（誤削除防止） |
# MAGIC
# MAGIC ## 注意
# MAGIC - `CONFIRM_DELETE = True` に変更しないと削除は実行されません
# MAGIC - Lakebase プロジェクトの削除は全データを失うため、
# MAGIC   実行する場合は `DELETE_LAKEBASE_PROJECT = True` も明示的に設定してください

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,削除フラグ
# ==============================================================
# 削除の実行制御
# ==============================================================
CONFIRM_DELETE = False           # True にすると削除が実行される
DELETE_LAKEBASE_PROJECT = False  # True にすると Lakebase プロジェクト自体も削除

# COMMAND ----------

# DBTITLE 1,Lakebase 検索テーブルの削除
# ==============================================================
# Lakebase 内の検索テーブルを削除
# ==============================================================
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

def pg_api(method, path, body=None, query=None):
    return w.api_client.do(method, f"/api/2.0/postgres{path}", body=body, query=query)

if not CONFIRM_DELETE:
    print("ℹ️ CONFIRM_DELETE = False のためスキップ（ドライラン）")
else:
    try:
        import psycopg
        host = pg_api("GET", f"/{LAKEBASE_ENDPOINT_PATH}")["status"]["hosts"]["host"]
        token = pg_api("POST", "/credentials", body={"endpoint": LAKEBASE_ENDPOINT_PATH})["token"]
        with psycopg.connect(
            host=host, dbname=LAKEBASE_PG_DATABASE,
            user=w.current_user.me().user_name, password=token,
            sslmode="require", autocommit=True,
        ) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")
        print(f"✅ 削除: {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}")
    except Exception as e:
        print(f"⚠️ Lakebase テーブル削除をスキップ: {e}")

# COMMAND ----------

# DBTITLE 1,メモリストアの削除
# ==============================================================
# UC メモリストアの削除（06c で作成）
# ==============================================================
if not CONFIRM_DELETE:
    print("ℹ️ CONFIRM_DELETE = False のためスキップ（ドライラン）")
else:
    try:
        w.api_client.do(
            "DELETE",
            f"/api/2.1/unity-catalog/memory-stores/{MEMORY_STORE_FULL_NAME}")
        print(f"✅ 削除: メモリストア {MEMORY_STORE_FULL_NAME}")
    except Exception as e:
        print(f"⚠️ メモリストア削除をスキップ（存在しない可能性）: {e}")

# COMMAND ----------

# DBTITLE 1,Genie スペースの削除
# ==============================================================
# Genie スペースの削除（07b で作成）
# ==============================================================
GENIE_SPACE_NAME = "製造ドキュメント検索 - content search ハンズオン"

if not CONFIRM_DELETE:
    print("ℹ️ CONFIRM_DELETE = False のためスキップ（ドライラン）")
else:
    deleted = False
    for space in (w.genie.list_spaces().spaces or []):
        if space.title == GENIE_SPACE_NAME:
            w.genie.trash_space(space.space_id)
            print(f"✅ 削除: Genie スペース {GENIE_SPACE_NAME} ({space.space_id})")
            deleted = True
            break
    if not deleted:
        print(f"ℹ️ Genie スペース '{GENIE_SPACE_NAME}' は見つかりませんでした")

# COMMAND ----------

# DBTITLE 1,Lakebase プロジェクトの削除（オプション）
# ==============================================================
# Lakebase プロジェクト全体の削除（オプション・要注意）
# ==============================================================
# 全ブランチ・エンドポイント・データが失われます。
# DELETE_LAKEBASE_PROJECT = True の場合のみ実行。
if not (CONFIRM_DELETE and DELETE_LAKEBASE_PROJECT):
    print(f"ℹ️ Lakebase プロジェクト '{LAKEBASE_PROJECT_ID}' は残します")
    print("   削除する場合は DELETE_LAKEBASE_PROJECT = True に設定して再実行")
else:
    try:
        pg_api("DELETE", f"/projects/{LAKEBASE_PROJECT_ID}")
        print(f"✅ 削除: Lakebase プロジェクト {LAKEBASE_PROJECT_ID}")
    except Exception as e:
        print(f"⚠️ プロジェクト削除に失敗: {e}")

# COMMAND ----------

# DBTITLE 1,完了
# ==============================================================
if CONFIRM_DELETE:
    print("✅ 99b_cleanup_alt 完了")
else:
    print("ドライラン完了。実際に削除するには CONFIRM_DELETE = True に変更してください。")
