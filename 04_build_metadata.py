# Databricks notebook source
# DBTITLE 1,04 メタデータ構築: 紹介
# MAGIC %md
# MAGIC # 04_build_metadata: チャンク化と検索用テーブル作成
# MAGIC
# MAGIC ## 目的
# MAGIC - 全ドキュメントを Vector Search 用にチャンク化
# MAGIC - `doc_chunks` テーブルを作成（CDF 有効・プライマリキー付き）
# MAGIC - メタデータ（製品ID・ドキュメント種別）をチャンクに埋め込み
# MAGIC
# MAGIC ## 所要時間目安: 10分
# MAGIC
# MAGIC ## 前提
# MAGIC - 03 ノートブックが実行済み（documents テーブルに全ドキュメントが登録済み）
# MAGIC
# MAGIC ## 製造業におけるチャンク化の意義
# MAGIC 製造業の技術ドキュメントは「どの製品の、どの試験の、どのページ」という文脈が重要です。  
# MAGIC チャンクにメタデータを埋め込むことで、検索結果から即座に「関連する図・波形・仕様書」にたどり着けます。

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,チャンク化ロジック
# ==============================================================
# ドキュメントのチャンク化
# ==============================================================
# 製造業実務: 各ドキュメントを検索可能な単位（チャンク）に分割し、
# 製品ID・ドキュメント種別をメタデータとして埋め込む。
import os, re
from pyspark.sql import Row

# documents テーブルから全ドキュメントを取得
docs_df = spark.sql(f"SELECT * FROM {FQ_DOCUMENTS}").collect()
print(f"処理対象ドキュメント: {len(docs_df)} 件")

# excel_cells からシート単位のテキストを取得
excel_text_by_doc = {}
try:
    cells_df = spark.sql(f"""
        SELECT file_name, sheet, 
               CONCAT_WS(' ', COLLECT_LIST(value)) as sheet_text
        FROM {FQ_EXCEL_CELLS}
        GROUP BY file_name, sheet
    """).collect()
    for row in cells_df:
        key = row.file_name
        if key not in excel_text_by_doc:
            excel_text_by_doc[key] = []
        excel_text_by_doc[key].append((row.sheet, row.sheet_text))
except Exception as e:
    print(f"⚠️ excel_cells 取得スキップ: {e}")

# チャンク生成
CHUNK_SIZE = 800  # 文字数
chunks = []
chunk_id = 0

for doc in docs_df:
    product_ids_str = ",".join(doc.product_ids) if doc.product_ids else ""
    doc_id = doc.doc_id
    doc_type = doc.doc_type
    file_path = doc.file_path
    
    # Excel はシート単位でチャンク化
    if doc_type == "excel" and doc_id in excel_text_by_doc:
        for sheet_name, sheet_text in excel_text_by_doc[doc_id]:
            # メタデータヘッダーを埋め込み
            header = (f"[ファイル: {doc_id}] "
                     f"[製品ID: {product_ids_str}] "
                     f"[種別: {doc_type}]\n\n"
                     f"[シート: {sheet_name}]\n")
            content = header + sheet_text[:CHUNK_SIZE]
            chunks.append(Row(
                chunk_id=chunk_id, doc_id=doc_id,
                content=content, product_ids_str=product_ids_str,
                doc_type=doc_type, file_path=file_path
            ))
            chunk_id += 1
    else:
        # 非 Excel: summary をチャンク化
        header = (f"[ファイル: {doc_id}] "
                 f"[製品ID: {product_ids_str}] "
                 f"[種別: {doc_type}]\n\n")
        text = doc.summary or doc.title or ""
        # 大きなテキストは複数チャンクに分割
        for i in range(0, max(len(text), 1), CHUNK_SIZE):
            chunk_text = text[i:i+CHUNK_SIZE]
            content = header + chunk_text
            chunks.append(Row(
                chunk_id=chunk_id, doc_id=doc_id,
                content=content, product_ids_str=product_ids_str,
                doc_type=doc_type, file_path=file_path
            ))
            chunk_id += 1

print(f"\nチャンク生成完了: {len(chunks)} チャンク")
print(f"  Excel由来: {sum(1 for c in chunks if c.doc_type=='excel')}")
print(f"  Word由来: {sum(1 for c in chunks if c.doc_type=='word')}")
print(f"  PPT由来: {sum(1 for c in chunks if c.doc_type=='pptx')}")
print(f"  PDF由来: {sum(1 for c in chunks if c.doc_type=='pdf')}")
print(f"  TIFF由来: {sum(1 for c in chunks if c.doc_type=='tiff')}")
print(f"  CSV由来: {sum(1 for c in chunks if c.doc_type=='csv')}")

# COMMAND ----------

# DBTITLE 1,doc_chunks テーブル作成
# ==============================================================
# doc_chunks テーブル作成（CDF 有効・プライマリキー付き）
# ==============================================================
# Vector Search Delta Sync の要件:
#   1. Change Data Feed (CDF) が有効
#   2. プライマリキーが存在

# テーブルが既存なら削除して再作成（ハンズオンのやり直しに対応）
spark.sql(f"DROP TABLE IF EXISTS {FQ_DOC_CHUNKS}")

df_chunks = spark.createDataFrame(chunks)
df_chunks.write.saveAsTable(FQ_DOC_CHUNKS)

# CDF 有効化
spark.sql(f"""
    ALTER TABLE {FQ_DOC_CHUNKS} 
    SET TBLPROPERTIES (delta.enableChangeDataFeed = true)
""")

# プライマリキー制約追加
spark.sql(f"""
    ALTER TABLE {FQ_DOC_CHUNKS}
    ADD CONSTRAINT pk_chunk_id PRIMARY KEY (chunk_id)
""")

print(f"✅ {FQ_DOC_CHUNKS} 作成完了")
print(f"   チャンク数: {df_chunks.count()}")
print(f"   CDF: 有効")
print(f"   Primary Key: chunk_id")

# COMMAND ----------

# DBTITLE 1,検証
# ==============================================================
# 検証
# ==============================================================
# テーブルプロパティ確認
print("テーブルプロパティ:")
props = spark.sql(f"SHOW TBLPROPERTIES {FQ_DOC_CHUNKS}").collect()
for p in props:
    if 'change' in p.key.lower():
        print(f"  {p.key} = {p.value}")

# サンプル表示
print("\nチャンクサンプル:")
display(spark.sql(f"""
    SELECT chunk_id, doc_id, doc_type, product_ids_str, 
           LEFT(content, 80) as content_preview
    FROM {FQ_DOC_CHUNKS} 
    ORDER BY chunk_id
    LIMIT 5
"""))

# アサーション
chunk_count = spark.sql(f"SELECT COUNT(*) as cnt FROM {FQ_DOC_CHUNKS}").first().cnt
assert chunk_count >= 20, f"チャンク数不足: {chunk_count}"
print(f"\n✅ 04_build_metadata 完了: {chunk_count} チャンク作成済み")
