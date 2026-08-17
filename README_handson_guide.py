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
