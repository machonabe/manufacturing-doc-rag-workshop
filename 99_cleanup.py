# Databricks notebook source
# DBTITLE 1,99 クリーンアップ
# MAGIC %md
# MAGIC # 99_cleanup: リソース削除
# MAGIC
# MAGIC ## 目的
# MAGIC ハンズオンで作成したリソースを削除します。
# MAGIC
# MAGIC ## 注意
# MAGIC - `CONFIRM_DELETE = True` に変更しないと削除は実行されません
# MAGIC - Free Edition では VS エンドポイントは貴重（1個制限）なので、既定では残します
