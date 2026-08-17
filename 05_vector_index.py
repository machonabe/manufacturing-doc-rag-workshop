# Databricks notebook source
# DBTITLE 1,05 Vector Search インデックス: 紹介
# MAGIC %md
# MAGIC # 05_vector_index: Vector Search インデックス作成
# MAGIC
# MAGIC ## 目的
# MAGIC - VS エンドポイントの準備完了を確認
# MAGIC - `doc_chunks` テーブルに Delta Sync インデックスを作成
# MAGIC - インデックスが READY になるまで待機
# MAGIC
# MAGIC ## 所要時間目安: 5〜10分（エンドポイント事前作成済みの場合）
# MAGIC
# MAGIC ## 前提
# MAGIC - 01 ノートブックで VS エンドポイントが作成済み
# MAGIC - 04 ノートブックで `doc_chunks` テーブルが作成済み
# MAGIC
# MAGIC ## 製造業における Vector Search の価値
# MAGIC 「あの製品の試験結果は？」「このエラーコードの原因は？」という自然言語の問いから、  
# MAGIC 関連する仕様書・図・波形を即座に特定する——それがセマンティック検索の力です。

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,VS エンドポイント状態確認
# ==============================================================
# VS エンドポイントの準備完了を確認
# ==============================================================
import time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

def wait_for_endpoint(endpoint_name, timeout_min=30):
    """VS エンドポイントが ONLINE になるまで待機"""
    start = time.time()
    while (time.time() - start) < timeout_min * 60:
        ep = w.vector_search_endpoints.get_endpoint(endpoint_name)
        state = ep.endpoint_status.state.value
        if state == "ONLINE":
            print(f"✅ VS エンドポイント ONLINE: {endpoint_name}")
            return True
        print(f"   待機中... ({state}) - 経過: {int(time.time()-start)}s")
        time.sleep(30)
    raise TimeoutError(f"VS エンドポイントが {timeout_min}分以内に ONLINE になりませんでした")

wait_for_endpoint(VS_ENDPOINT_NAME)

# COMMAND ----------

# DBTITLE 1,Delta Sync インデックス作成
# ==============================================================
# Delta Sync インデックス作成（マネージドエンベディング）
# ==============================================================
# 製造業実務: 埋め込みモデル (databricks-gte-large-en) が自動で
# content 列をベクトル化し、類似検索を可能にします。

# 既存インデックスがあれば削除して再作成
try:
    existing = w.vector_search_indexes.get_index(VS_INDEX_NAME)
    print(f"⚠️ 既存インデックスを削除: {VS_INDEX_NAME}")
    w.vector_search_indexes.delete_index(VS_INDEX_NAME)
    time.sleep(10)  # 削除完了を待つ
except Exception:
    pass  # 存在しない場合はスキップ

print(f"🚀 インデックス作成開始: {VS_INDEX_NAME}")
print(f"   ソーステーブル: {FQ_DOC_CHUNKS}")
print(f"   埋め込みモデル: {EMBEDDING_ENDPOINT}")
print(f"   プライマリキー: chunk_id")

w.vector_search_indexes.create_index(
    name=VS_INDEX_NAME,
    endpoint_name=VS_ENDPOINT_NAME,
    primary_key="chunk_id",
    index_type="DELTA_SYNC",
    delta_sync_index_spec={
        "source_table": FQ_DOC_CHUNKS,
        "embedding_source_columns": [
            {
                "name": "content",
                "embedding_model_endpoint_name": EMBEDDING_ENDPOINT
            }
        ],
        "pipeline_type": "TRIGGERED",
        "columns_to_sync": ["chunk_id", "doc_id", "content", "product_ids_str", "doc_type", "file_path"]
    }
)
print("✅ インデックス作成リクエスト送信完了")

# COMMAND ----------

# DBTITLE 1,インデックス READY 待機
# ==============================================================
# インデックスが READY になるまで待機
# ==============================================================
def wait_for_index(index_name, timeout_min=20):
    """VS インデックスが検索可能になるまで待機"""
    start = time.time()
    while (time.time() - start) < timeout_min * 60:
        try:
            idx = w.vector_search_indexes.get_index(index_name)
            if idx.status.ready:
                print(f"✅ インデックス READY: {index_name}")
                return True
            msg = idx.status.message or ""
            print(f"   待機中... 経過: {int(time.time()-start)}s | {msg[:60]}")
        except Exception as e:
            print(f"   確認中... {e}")
        time.sleep(30)
    raise TimeoutError(f"インデックスが {timeout_min}分以内に READY になりませんでした")

wait_for_index(VS_INDEX_NAME)

# COMMAND ----------

# DBTITLE 1,検証: テストクエリ
# ==============================================================
# 検証: テストクエリで検索動作確認
# ==============================================================
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)
idx = vsc.get_index(endpoint_name=VS_ENDPOINT_NAME, index_name=VS_INDEX_NAME)

# テスト検索
results = idx.similarity_search(
    query_text="SNS-100 の動作温度範囲",
    columns=["chunk_id", "doc_id", "product_ids_str", "doc_type"],
    num_results=3
)
hits = results.get('result', {}).get('data_array', [])
print(f"テストクエリ: 'SNS-100 の動作温度範囲'")
print(f"  ヒット数: {len(hits)}")
for h in hits:
    print(f"  - chunk_id={h[0]}, doc={h[1]}, products={h[2]}, type={h[3]}")

assert len(hits) >= 1, "検索結果が 0 件です"
print(f"\n✅ 05_vector_index 完了: インデックスが検索可能です")
print("→ 次の 06_rag_query ノートブックで RAG 検索を体験しましょう！")
