# Databricks notebook source
# DBTITLE 1,ハンズオンガイド
# MAGIC %md
# MAGIC # 🏭 製造業向けドキュメント検索 RAG ハンズオン
# MAGIC
# MAGIC ## 概要
# MAGIC 製造業の技術ドキュメント（試験成績書・Word仕様書・PDFデータシート・ブロック図）を Databricks 上で一元管理し、  
# MAGIC **自然言語で検索 → 関連する図・波形・仕様書を即座に表示**する体験をハンズオンで学びます。
# MAGIC
# MAGIC ## 対象者
# MAGIC - 製造業の設計・品質エンジニア
# MAGIC - データエンジニア・データサイエンティスト
# MAGIC - Databricks で RAG システムを構築したい方
# MAGIC
# MAGIC ## 前提条件
# MAGIC - Databricks ワークスペースへのアクセス
# MAGIC - Unity Catalog が有効
# MAGIC - サーバレスコンピュートが利用可能
# MAGIC
# MAGIC ## 所要時間: 約 60〜90 分
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## ⏱️ 最初に読んでください: 効率的な進め方
# MAGIC
# MAGIC Vector Search エンドポイントの作成には **10〜20分** かかります。  
# MAGIC 待ち時間を無駄にしないため、以下の順序で進めてください:
# MAGIC
# MAGIC 1. **01 の「VS エンドポイント事前作成」セルまで実行** → 完了を待たずに次へ
# MAGIC 2. 01 の残りと 02〜04 を順番に進める（その間にバックグラウンドで完了）
# MAGIC 3. 05 に到達した時点でエンドポイントが準備完了している
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## ノートブック構成
# MAGIC
# MAGIC | # | ノートブック | 内容 | 所要時間 |
# MAGIC |---|---|---|---|
# MAGIC | 00 | `00_config` | 全体共通設定（カタログ・スキーマ・テーブル名） | - |
# MAGIC | 01 | `01_setup_and_sample_data` | 環境セットアップと合成データ生成 | 10分 |
# MAGIC | 02 | `02_extract_excel` | Excel 試験成績書からのメタデータ抽出 | 20分 |
# MAGIC | 03 | `03_extract_docs` | Word/PPT/PDF/TIFF/CSV からのテキスト抽出 | 10分 |
# MAGIC | 04 | `04_build_metadata` | チャンク化と検索用テーブル作成 | 10分 |
# MAGIC | 05 | `05_vector_index` | Vector Search インデックス作成 | 5〜10分 |
# MAGIC | 06 | `06_rag_query` | 自然言語検索 → 図・波形表示（ゴール体験） | 15分 |
# MAGIC | 07 | `07_genie_space` | Genie Space で構造化データ探索 | 5分 |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 1: 環境セットアップ (01)
# MAGIC
# MAGIC `01_setup_and_sample_data` を上から順に実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - Unity Catalog のスキーマ・ Volume 構成
# MAGIC - 製造業でよくある「フォーマット不統一」を意図的に再現（レイアウトA/B/C）
# MAGIC - VS エンドポイントの事前作成（← ここが重要！）
# MAGIC
# MAGIC **生成されるファイル:**
# MAGIC - Excel 試験成績書 × 6（埋め込みチャート・取消線・結合セル付き）
# MAGIC - Word 仕様書 × 3
# MAGIC - PowerPoint 設計レビュー × 2
# MAGIC - PDF データシート × 2
# MAGIC - TIFF ブロック図 × 3
# MAGIC - CSV 波形データ × 6
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 2: Excel メタデータ抽出 (02)
# MAGIC
# MAGIC `02_extract_excel` を実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - openpyxl で埋め込み画像を分離抽出
# MAGIC - 取り消し線（修正履歴）の検出 → メタデータ化
# MAGIC - ファイル名・セル内容から製品ID/試験IDを正規表現で抽出
# MAGIC
# MAGIC **作成されるテーブル:**
# MAGIC - `documents` - ドキュメント管理テーブル
# MAGIC - `media_assets` - 図・波形とファイルの紐付け
# MAGIC - `excel_cells` - セル単位メタデータ
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 3: ドキュメント抽出 (03)
# MAGIC
# MAGIC `03_extract_docs` を実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - python-docx / python-pptx / pypdf / Pillow で多様なフォーマットに対応
# MAGIC - TIFF ブロック図のサムネイル化
# MAGIC - 全ドキュメントを統一的に `documents` テーブルで管理
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 4: チャンク化 (04)
# MAGIC
# MAGIC `04_build_metadata` を実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - Vector Search に適したチャンクサイズの設計
# MAGIC - メタデータ（製品ID・ドキュメント種別）をチャンクに埋め込む意義
# MAGIC - Delta テーブルの CDF 有効化 + プライマリキー（VS の前提条件）
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 5: Vector Search インデックス (05)
# MAGIC
# MAGIC `05_vector_index` を実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - Delta Sync インデックス（マネージドエンベディング）の作成
# MAGIC - `databricks-gte-large-en` モデルによる自動ベクトル化
# MAGIC - インデックスが READY になるまでの待機パターン
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 6: RAG 検索体験 (06) ★ ゴール
# MAGIC
# MAGIC `06_rag_query` を実行します。
# MAGIC
# MAGIC **デモ質問例:**
# MAGIC - 「SNS-200 の過渡応答の試験結果と波形を見せて」
# MAGIC - 「SNS-100 の動作温度範囲は？根拠となる仕様書も教えて」
# MAGIC - 「取り消し線で修正された測定値を含むファイルはどれ？」
# MAGIC
# MAGIC **体験できること:**
# MAGIC - Vector Search でのセマンティック検索
# MAGIC - LLM による回答生成（出典付き）
# MAGIC - 関連するブロック図・波形チャートの即座表示
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## Step 7: Genie Space (07)
# MAGIC
# MAGIC `07_genie_space` を実行します。
# MAGIC
# MAGIC **学びのポイント:**
# MAGIC - 構造化データを自然言語で SQL 探索
# MAGIC - RAG（06）との使い分け:
# MAGIC   - 06: ドキュメントの中身を読む（セマンティック検索）
# MAGIC   - 07: データを集計する（SQLクエリ）
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## トラブルシューティング
# MAGIC
# MAGIC | 問題 | 対処 |
# MAGIC |---|---|
# MAGIC | VS エンドポイントが ONLINE にならない | 20分ほど待ってください。Free Edition では 1 エンドポイント制限があります |
# MAGIC | LLM ガードレールエラー | 製造業用語が安全フィルタに引っかかる場合があります。フォールバックで検索結果のみ表示されます |
# MAGIC | `ModuleNotFoundError` | `%pip install` 後に `dbutils.library.restartPython()` を実行してください |
# MAGIC | インデックスが READY にならない | `doc_chunks` テーブルに CDF と PK が設定されているか確認してください |
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## クリーンアップ
# MAGIC
# MAGIC ハンズオン終了後、`99_cleanup` を実行すると作成したリソースを削除できます。
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 次のステップ（本番適用に向けて）
# MAGIC
# MAGIC 1. **Knowledge Assistant でエージェント化** — 有償ワークスペースでは Agent Bricks を使ってノーコードでデプロイ可能
# MAGIC 2. **Box MCP / SharePoint 経由の自動取り込み** — 実データを Volume に自動インジェスト
# MAGIC 3. **Lakeflow SDP でパイプライン化** — 新規ドキュメント追加時に自動でインデックス更新

# COMMAND ----------

# DBTITLE 1,使用機能の解説
# MAGIC %md
# MAGIC ---
# MAGIC
# MAGIC # 📚 使用している機能の解説
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 1. Unity Catalog
# MAGIC
# MAGIC ### 仕組み
# MAGIC Unity Catalog は Databricks の統合データガバナンスレイヤーです。カタログ > スキーマ > テーブル/Volume の 3 階層構造で全データアセットを一元管理します。
# MAGIC
# MAGIC ### 本ハンズオンでの役割
# MAGIC - **Volume**: 生ファイル（Excel/Word/PDF/TIFF）の格納先。クラウドストレージ上のファイルを SQL パス（`/Volumes/catalog/schema/volume/`）でアクセス可能
# MAGIC - **テーブル**: 抽出したメタデータを Delta 形式で構造化保存
# MAGIC - **アクセス制御**: テーブル・ Volume 単位で権限管理が可能
# MAGIC
# MAGIC ### 利点
# MAGIC - ファイルと構造化データを同じガバナンスで管理
# MAGIC - リニージ（誰がいつ何を更新したか）の自動追跡
# MAGIC - ワークスペースをまたいだデータ共有が可能
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 2. Delta Lake（Change Data Feed + Primary Key）
# MAGIC
# MAGIC ### 仕組み
# MAGIC Delta Lake は ACID トランザクション対応のオープンソースストレージレイヤーです。Parquet + トランザクションログでバージョニングとタイムトラベルを実現します。
# MAGIC
# MAGIC ### Change Data Feed (CDF)
# MAGIC テーブルへの変更（INSERT/UPDATE/DELETE）を別のフォルダに記録する機能です。Vector Search の Delta Sync インデックスは、この CDF を読み取って「どの行が変更されたか」を検知し、変更分だけをインデックスに反映します。
# MAGIC
# MAGIC ### Primary Key (PK)
# MAGIC Vector Search が各ベクトルを一意に識別するために必要です。チャンクが更新されたとき、PK で古いベクトルを特定して置き換えます。
# MAGIC
# MAGIC ### 利点
# MAGIC - 全件再インデックス不要 → 差分同期で高速・低コスト
# MAGIC - データの信頼性（ACID）を保証しながら検索インデックスを最新に保つ
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 3. Databricks Vector Search
# MAGIC
# MAGIC ### 仕組み
# MAGIC Vector Search はテキストを高次元ベクトル（数値の配列）に変換し、「意味の近さ」で検索するマネージドサービスです。
# MAGIC
# MAGIC ```
# MAGIC テキスト → Embedding Model → [0.12, -0.34, 0.56, ...] (1024次元)
# MAGIC                                          ↓
# MAGIC                                ANN (Approximate Nearest Neighbor) 検索
# MAGIC                                          ↓
# MAGIC                                意味的に近いドキュメントを返却
# MAGIC ```
# MAGIC
# MAGIC ### コンポーネント
# MAGIC | コンポーネント | 役割 |
# MAGIC |---|---|
# MAGIC | **エンドポイント** | ベクトルインデックスをホストするコンピュートリソース |
# MAGIC | **Delta Sync インデックス** | Delta テーブルの変更を自動でベクトル化・同期 |
# MAGIC | **マネージドエンベディング** | Databricks がテキスト→ベクトル変換を自動実行 |
# MAGIC
# MAGIC ### 利点
# MAGIC - キーワード一致ではなく「意味」で検索（「過渡応答」で検索 → 「ステップ応答時間 210ms」のドキュメントがヒット）
# MAGIC - Delta テーブルと自動同期 → ドキュメント追加時に再インデックス不要
# MAGIC - 埋め込みモデルの管理不要（マネージド）
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 4. Foundation Model APIs（Pay-per-token）
# MAGIC
# MAGIC ### 仕組み
# MAGIC Databricks が提供する基盤モデルを、トークン単位の従量課金で利用できるサービスです。インフラの構築・管理が不要で、API を呼ぶだけで利用できます。
# MAGIC
# MAGIC ### 本ハンズオンで使用するモデル
# MAGIC | モデル | 用途 | 特徴 |
# MAGIC |---|---|---|
# MAGIC | `databricks-gte-large-en` | テキストのベクトル化 | 1024次元, 8192トークンコンテキスト |
# MAGIC | `databricks-meta-llama-3-3-70b-instruct` | 回答生成 | 70Bパラメータ, 日本語対応 |
# MAGIC
# MAGIC ### 利点
# MAGIC - GPU クラスターのプロビジョニング不要
# MAGIC - OpenAI 互換 API（`/serving-endpoints`）で既存コードの移行が容易
# MAGIC - データが Databricks 環境外に出ない（セキュリティ）
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 5. RAG（Retrieval-Augmented Generation）
# MAGIC
# MAGIC ### 仕組み
# MAGIC LLM 単体では「知らないこと」に答えられません。RAG は「まず関連ドキュメントを検索し、それを文脈として LLM に渡す」パターンです。
# MAGIC
# MAGIC ```
# MAGIC ユーザー質問
# MAGIC     │
# MAGIC     ▼
# MAGIC ┌───────────────────────┐
# MAGIC │ 1. Retrieval            │  ← Vector Search で関連チャンクを取得
# MAGIC │    (セマンティック検索) │
# MAGIC └───────────┬───────────┘
# MAGIC             │
# MAGIC             ▼
# MAGIC ┌───────────────────────┐
# MAGIC │ 2. Augmentation         │  ← 検索結果をプロンプトに埋め込み
# MAGIC │    (コンテキスト付与)  │
# MAGIC └───────────┬───────────┘
# MAGIC             │
# MAGIC             ▼
# MAGIC ┌───────────────────────┐
# MAGIC │ 3. Generation           │  ← LLM が出典付きで回答生成
# MAGIC │    (回答生成)         │
# MAGIC └───────────────────────┘
# MAGIC ```
# MAGIC
# MAGIC ### 利点
# MAGIC - LLM のハルシネーション（嘲り）を防止 — 実際のドキュメントに基づく回答のみ
# MAGIC - 出典を明示できる — 「どのファイルのどの部分から」が追跡可能
# MAGIC - モデルのファインチューニング不要 — ドキュメントを追加するだけで知識が拡張
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 6. Genie Space
# MAGIC
# MAGIC ### 仕組み
# MAGIC Genie Space は自然言語を SQL に変換して実行するツールです。登録されたテーブルのスキーマを理解し、ユーザーの質問に対して適切な SQL を自動生成・実行します。
# MAGIC
# MAGIC ```
# MAGIC 「製品ごとのドキュメント数は？」
# MAGIC     │
# MAGIC     ▼  Genie が SQL を生成
# MAGIC     SELECT product_id, COUNT(*) FROM documents GROUP BY product_id
# MAGIC     │
# MAGIC     ▼  SQL Warehouse で実行
# MAGIC     結果テーブルを表示
# MAGIC ```
# MAGIC
# MAGIC ### RAG（06）との使い分け
# MAGIC | 観点 | RAG (06) | Genie Space (07) |
# MAGIC |---|---|---|
# MAGIC | 得意なこと | ドキュメントの中身を読む | データを集計・分析 |
# MAGIC | 検索方式 | セマンティック（意味） | SQL（完全一致・集計） |
# MAGIC | 質問例 | 「過渡応答の試験結果は？」 | 「製品ごとの試験件数は？」 |
# MAGIC | 出力 | 自然言語の回答 + 図・波形 | テーブル・グラフ |
# MAGIC
# MAGIC ### 利点
# MAGIC - 非エンジニア（品質管理部門等）が SQL を知らなくてもデータ探索可能
# MAGIC - テーブルを登録するだけでセットアップ完了
# MAGIC - SQL が見えるので「何をやったか」が透明
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 7. ドキュメント処理ライブラリ
# MAGIC
# MAGIC ### 各ライブラリの役割
# MAGIC | ライブラリ | 対象 | 何ができるか |
# MAGIC |---|---|---|
# MAGIC | `openpyxl` | Excel (.xlsx) | セル値・書式（取消線）・埋め込み画像・結合セルの読み取り |
# MAGIC | `python-docx` | Word (.docx) | 段落テキスト・表・スタイルの抽出 |
# MAGIC | `python-pptx` | PowerPoint (.pptx) | スライド内テキストフレームの抽出 |
# MAGIC | `pypdf` | PDF (.pdf) | ページ単位のテキスト抽出 |
# MAGIC | `Pillow` | TIFF/PNG | 画像のリサイズ・サムネイル生成 |
# MAGIC
# MAGIC ### 製造業でこれらが重要な理由
# MAGIC 製造業の技術ドキュメントは「フォーマットが部署・時期・担当者によってバラバラ」という現実があります。  
# MAGIC 完璧な構造化よりも「どの製品・どの試験に紐付くか」というメタデータを正規表現で抽出し、検索可能にすることが最優先です。
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 8. チャンク化の設計思想
# MAGIC
# MAGIC ### なぜチャンク化が必要か
# MAGIC 埋め込みモデルには入力トークン数の上限があります（`databricks-gte-large-en` は 8192 トークン）。また、長いテキストをそのままベクトル化すると意味が「平均化」されて検索精度が低下します。
# MAGIC
# MAGIC ### 本ハンズオンの設計
# MAGIC - **チャンクサイズ**: 800文字（製造業の試験項目単位に近い粒度）
# MAGIC - **メタデータ埋め込み**: 各チャンクの先頭に `[製品ID: SNS-200] [種別: excel]` を付与
# MAGIC - **Excel はシート単位**: 「測定結果」シートと「総合試験」シートを別チャンクに
# MAGIC
# MAGIC ### 利点
# MAGIC - 検索結果から即座に「どの製品のどのファイルか」が分かる
# MAGIC - メタデータによるフィルタリングが可能（「SNS-200 のドキュメントだけ」など）
# MAGIC - 関連する図・波形へのナビゲーションが容易
