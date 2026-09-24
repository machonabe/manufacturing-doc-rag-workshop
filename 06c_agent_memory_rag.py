# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,06c Agent Memory RAG: 会話の記憶を持つエージェント
# MAGIC %md
# MAGIC # 06c_agent_memory_rag: Lakebase 検索 + Agent Memory のエージェント型 RAG
# MAGIC
# MAGIC ## 目的
# MAGIC - 06b の Lakebase 検索に **Agent Memory**（会話の長期記憶）を組み合わせ、
# MAGIC   「前の会話を覚えている」エージェント型 RAG を体験する
# MAGIC - Agent Memory は UC の **メモリストア** として管理され、
# MAGIC   スコープ（ユーザー単位等）で記憶が分離される
# MAGIC
# MAGIC ## 所要時間目安: 15分
# MAGIC
# MAGIC ## 前提
# MAGIC - **有償ワークスペース**
# MAGIC - 05b ノートブック実行済み（Lakebase にチャンク＋埋め込みがロード済み）
# MAGIC - スキーマに対する `CREATE MEMORY STORE` 権限（カタログ/スキーマ所有者なら保有）
# MAGIC
# MAGIC ## 06/06b との違い
# MAGIC | 観点 | 06/06b (RAG) | 06c (Agent Memory RAG) |
# MAGIC |---|---|---|
# MAGIC | 会話の記憶 | なし（毎回独立した質問） | メモリストアに永続化 |
# MAGIC | 「その製品は？」のような照応 | 解決できない | 記憶から解決できる |
# MAGIC | ユーザー固有の文脈 | なし | スコープ単位で記憶を分離 |
# MAGIC | API | chat completions | Responses API + conversations |
# MAGIC
# MAGIC ## 製造業における Agent Memory の価値
# MAGIC 「さっき調べた製品の他の仕様も見せて」「いつもの形式でレポート化して」——
# MAGIC 現場の問い合わせは文脈依存の連続した会話です。
# MAGIC メモリストアが記憶を保持するため、エージェントは都度説明し直す必要がありません。

# COMMAND ----------

# DBTITLE 1,ライブラリインストール
# MAGIC %pip install "psycopg[binary]>=3.1" openai databricks-openai --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,設定読み込み
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,メモリストアの作成
# ==============================================================
# Agent Memory（UC メモリストア）の作成
# ==============================================================
# メモリストアは REST API で作成する UC セキュアブル。
# 権限: 親スキーマに対する CREATE MEMORY STORE が必要。
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

def uc_api(method, path, body=None, query=None):
    """Unity Catalog REST API 呼び出しヘルパー"""
    return w.api_client.do(method, f"/api/2.1/unity-catalog{path}", body=body, query=query)

memory_store_exists = False
try:
    store = uc_api("GET", f"/memory-stores/{MEMORY_STORE_FULL_NAME}")
    memory_store_exists = True
    print(f"✅ 既存メモリストアを再利用: {MEMORY_STORE_FULL_NAME}")
except Exception as e:
    err = str(e)
    if "404" in err or "NOT_FOUND" in err.upper() or "does not exist" in err.lower():
        print(f"メモリストア {MEMORY_STORE_FULL_NAME} は存在しません → 作成します")
    else:
        raise

if not memory_store_exists:
    try:
        uc_api("POST", "/memory-stores", body={
            "name": MEMORY_STORE_NAME,
            "catalog_name": CATALOG,
            "schema_name": SCHEMA,
            "description": "製造業ドキュメント検索エージェントの長期記憶（ハンズオン）",
        })
        print(f"✅ メモリストア作成完了: {MEMORY_STORE_FULL_NAME}")
    except Exception as e:
        err = str(e)
        if "ALREADY_EXISTS" in err.upper() or "already exists" in err.lower():
            print(f"✅ メモリストアは既に存在: {MEMORY_STORE_FULL_NAME}")
        elif "PERMISSION" in err.upper() or "CREATE MEMORY STORE" in err.upper():
            print("⚠️ CREATE MEMORY STORE 権限がありません。管理者に以下を依頼してください:")
            print(f"   GRANT CREATE MEMORY STORE ON SCHEMA {CATALOG}.{SCHEMA} TO `<あなたのユーザー>`")
            raise
        else:
            raise

# COMMAND ----------

# DBTITLE 1,Lakebase 検索の準備（06b と同じ）
# ==============================================================
# Lakebase 接続ヘルパー + 検索関数（06b と同一ロジック）
# ==============================================================
import psycopg, openai

def pg_api(method, path, body=None, query=None):
    return w.api_client.do(method, f"/api/2.0/postgres{path}", body=body, query=query)

def get_conn():
    host = pg_api("GET", f"/{LAKEBASE_ENDPOINT_PATH}")["status"]["hosts"]["host"]
    token = pg_api("POST", "/credentials", body={"endpoint": LAKEBASE_ENDPOINT_PATH})["token"]
    return psycopg.connect(
        host=host, dbname=LAKEBASE_PG_DATABASE,
        user=w.current_user.me().user_name, password=token,
        sslmode="require", autocommit=True,
    )

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
fm_client = openai.OpenAI(
    api_key=ctx.apiToken().get(),
    base_url=f"{ctx.apiUrl().get()}/serving-endpoints",
)

def search_chunks(question, num_results=5):
    """Lakebase ベクトル検索（06b の search_chunks と同一）"""
    resp = fm_client.embeddings.create(model=EMBEDDING_ENDPOINT, input=[question])
    qvec_str = "[" + ",".join(f"{v:.6f}" for v in resp.data[0].embedding) + "]"
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT chunk_id, doc_id, content, product_ids_str, file_path
                FROM {LAKEBASE_PG_SCHEMA}.{LAKEBASE_TABLE_CHUNKS}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""",
            (qvec_str, num_results),
        ).fetchall()

print("✅ Lakebase 検索の準備完了")

# COMMAND ----------

# DBTITLE 1,Agent Memory エージェントの定義
# ==============================================================
# メモリストアを使うエージェント（Responses API + conversations）
# ==============================================================
# databricks-openai の conversations / responses API を使用。
# conversation に memory_store と scope を紐付けると、
# 会話から得た記憶が自動的にメモリストアへ保存・参照される。
from databricks_openai import DatabricksOpenAI

agent_client = DatabricksOpenAI(workspace_client=w, use_ai_gateway=True)
user_id = str(w.current_user.me().id)

def new_conversation():
    """このユーザーのスコープに紐付いた会話を作成"""
    return agent_client.conversations.create(
        extra_body={
            "memory_store": {"name": MEMORY_STORE_FULL_NAME},
            "scope": {"kind": "user", "value": user_id},
        },
    )

AGENT_INSTRUCTIONS = (
    "あなたは製造業の技術ドキュメントに基づいて回答するアシスタントです。"
    "日本語で、出典ファイル名を明記して簡潔に回答してください。"
    "ユーザーの名前・所属・関心のある製品など、会話で得た情報は記憶して活用してください。"
)

def ask_agent(conversation_id, question, use_rag=True):
    """
    質問 → (任意で) Lakebase 検索 → コンテキスト付きでエージェントに問い合わせ。
    会話 ID が同じなら記憶が引き継がれる。
    """
    if use_rag:
        hits = search_chunks(question, num_results=5)
        context = "\n---\n".join([h[2][:500] for h in hits])
        sources = ", ".join(sorted(set(h[1] for h in hits)))
        prompt = f"質問: {question}\n\n参考情報（検索結果）:\n{context}\n\n出典: {sources}"
    else:
        hits = []
        prompt = question

    response = agent_client.responses.create(
        model=AGENT_MODEL,
        conversation=conversation_id,
        instructions=AGENT_INSTRUCTIONS,
        input=[{"type": "message", "role": "user", "content": prompt}],
    )
    # Responses API のテキスト取り出し（SDK バージョン差を吸収）
    answer_text = getattr(response, "output_text", None)
    if not answer_text:
        parts = []
        for item in getattr(response, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    parts.append(c.text)
        answer_text = "\n".join(parts) or str(response)
    return answer_text, hits

print("✅ エージェント定義完了 (new_conversation / ask_agent)")

# COMMAND ----------

# DBTITLE 1,デモ: 記憶を持つ会話
# ==============================================================
# デモ: 会話の記憶が引き継がれることを体験
# ==============================================================
# ポイント: 同じ conversation で問い続けると、
# 「その製品」「さっきの結果」といった照応が解決される。
conversation = new_conversation()
print(f"会話開始: conversation_id = {conversation.id}")

# --- Turn 1: 名前・所属とあわせて質問 ---
q1 = "私は品質保証部の渡辺です。SNS-200 の過渡応答の試験結果を教えてください。"
print(f"\n{'='*60}\n🧑 Turn 1: {q1}\n{'='*60}")
a1, hits1 = ask_agent(conversation.id, q1)
print(f"\n🤖 回答:\n{a1}")

# --- Turn 2: 照応（「その製品」→ SNS-200 を記憶から解決）---
q2 = "その製品の供給電圧と動作温度範囲も教えて。"
print(f"\n{'='*60}\n🧑 Turn 2: {q2}\n{'='*60}")
a2, hits2 = ask_agent(conversation.id, q2)
print(f"\n🤖 回答:\n{a2}")

# --- Turn 3: 記憶の確認 ---
q3 = "私の名前と所属を覚えていますか？"
print(f"\n{'='*60}\n🧑 Turn 3: {q3}\n{'='*60}")
a3, _ = ask_agent(conversation.id, q3, use_rag=False)
print(f"\n🤖 回答:\n{a3}")

# COMMAND ----------

# DBTITLE 1,記憶の中身を直接検査
# ==============================================================
# メモリストアに保存された記憶を REST API で直接検査
# ==============================================================
# エージェントが何を覚えたかは entries:search API で確認できる。
# 運用時の監査・デバッグに使えるポイント。
print(f"▶ スコープ {user_id} の記憶を検索:")
try:
    result = uc_api(
        "POST",
        f"/memory-stores/{MEMORY_STORE_FULL_NAME}/entries:search",
        body={"scope": user_id, "query": "ユーザー 所属 製品", "top_k": 10},
    )
    entries = result.get("entries", []) if isinstance(result, dict) else []
    if entries:
        for e in entries:
            print(f"  ・{e.get('path', '?')}: {str(e.get('contents', ''))[:100]}")
    else:
        print("  （まだ記憶が保存されていません。会話を重ねると蓄積されます）")
except Exception as e:
    print(f"  ⚠️ 記憶の検索に失敗: {e}")

# COMMAND ----------

# DBTITLE 1,まとめ
# MAGIC %md
# MAGIC ## Agent Memory パターンのまとめ
# MAGIC
# MAGIC | 要素 | 役割 |
# MAGIC |---|---|
# MAGIC | **メモリストア** (UC) | 記憶の永続化コンテナ。ガバナンス・権限は UC に統合 |
# MAGIC | **スコープ** | 記憶の分離単位（`user` = ユーザー毎 / `shared` = 全員共有 / カスタム） |
# MAGIC | **conversation** | 会話の単位。同じ会話 ID なら記憶が引き継がれる |
# MAGIC | **Lakebase 検索** | 毎ターンの RAG コンテキスト供給（06b と同じ） |
# MAGIC
# MAGIC ### スコープの設計指針
# MAGIC - **user**: 個人の調査履歴・好みを記憶（このハンズオン）
# MAGIC - **shared**: チーム共通の知見（「この製品ラインの既知の問題」等）を全員で共有
# MAGIC - **カスタム**: `工場:ライン` 等の複合キーでテナント/拠点単位に分離
# MAGIC
# MAGIC ### セキュリティ注意
# MAGIC スコープは分離の仕組みでありアクセス制御ではありません。
# MAGIC サービスプリンシパルは全スコープにアクセスできるため、資格情報の管理に注意してください。
# MAGIC
# MAGIC ### 代替: セルフマネージドメモリ
# MAGIC LangGraph / OpenAI Agents SDK のテンプレートを使い、
# MAGIC Lakebase 上に自分で状態を持つ方式もあります（チェックポインティング等）。
# MAGIC マネージドメモリは運用レス、セルフマネージドは柔軟性が強みです。
