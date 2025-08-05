# 焼肉店オーダー管理システム

## 概要
このシステムは焼肉店向けのWebベースのオーダー管理システムです。座席管理、コース管理、商品管理、注文受付、タイマー管理などの機能を提供します。

## 主な機能

### 1. 管理機能 (/manage)
- 座席管理：座席番号の追加・編集・削除
- コース管理：コースの追加・編集・削除・表示/非表示切替
- 商品管理：コースごとの商品（カテゴリ/ID/名）の管理

### 2. 注文管理
- 座席別注文受付
- コース選択
- タイマー管理（注文時間・席時間）
- 注文履歴管理

### 3. スタッフ機能
- リアルタイムの注文状況確認
- 座席状態モニタリング
- タイマー管理
- 営業時間管理

## 技術スタック

### フロントエンド
- HTML/CSS
- JavaScript (Vanilla JS)
- レスポンシブデザイン

### バックエンド
- Python 3.x
- Flask
- SQLAlchemy
- MySQL

### データ管理
- JSON形式のファイル管理
  - seats.json: 座席情報
  - menus/*.json: コース・商品情報
  - settings.json: 営業時間設定

## セットアップ

1. 依存パッケージのインストール
```bash
pip install -r requirements.txt
```

2. データベースの初期化
```bash
flask db init
flask db migrate
flask db upgrade
```

3. 開発サーバーの起動
```bash
flask run
```

## API エンドポイント

### 座席管理
- GET /api/seats - 座席一覧取得
- POST /api/seats - 座席追加
- PUT /api/seats/<seat> - 座席編集
- DELETE /api/seats/<seat> - 座席削除

### コース管理
- GET /api/courses - コース一覧取得
- POST /api/courses - コース追加
- PUT /api/courses/<course_id> - コース編集
- DELETE /api/courses/<course_id> - コース削除

### 商品管理
- GET /api/dishes/<course_id> - 商品一覧取得
- POST /api/dishes/<course_id> - 商品追加
- PUT /api/dishes/<course_id>/<dish_id> - 商品編集
- DELETE /api/dishes/<course_id>/<dish_id> - 商品削除

## 注意事項

- 本番環境では必ずデバッグモードを無効化してください
- データベース接続情報は環境変数で管理することを推奨します
- 定期的なバックアップを推奨します

## ライセンス
MIT License

## 作者
Atsuto Yano