# telepy（テレパイ）- テレアポ代行AIシステム

AIが自動で架電し、アポイントを取得したら人間にハンドオフするテレアポ代行サービスです。
加えて、依頼文からターゲット企業を探す **リスト作成** 機能を備えています。

## システム構成

| コンポーネント | 技術 |
|---|---|
| バックエンド | Python + FastAPI |
| 通話 | Twilio（発信・録音） |
| 音声認識(STT) | Deepgram |
| 音声合成(TTS) | ElevenLabs |
| 会話AI | Claude API（claude-sonnet-4-20250514） |
| DB | Supabase |
| 通知 | Slack Webhook |

## 通話フロー

```
GREETING → QUALIFYING → PITCHING → CLOSING → HANDOFF（アポ確定）
                            ↓
                        OBJECTION（最大2回）→ REJECTED（終話）
```

相手が「人間と話したい」と言った場合、即座にHANDOFF状態に遷移します。

## リスト作成機能（企業リストビルダー）

「工務店・不動産のリストを、従業員10-20名・資本金1000万円以下・東京と神奈川で1000件」——
このような依頼文をそのまま貼り付けるだけで、条件に合う企業リストをCSVで作成します。
管理画面の **リスト作成** タブから利用できます。

### 仕組み

```
依頼文 → ① 条件抽出（Claude） → ② gBizINFOで検索 → ③ フィルタ/ランク付け → ④ CSV出力
                                                                          ↓
                                                              架電用CSV（架電管理へ）
```

1. **条件抽出**: 依頼文から 業種 / 従業員数 / 資本金 / 都道府県 / 件数 を構造化（Anthropic APIキーが
   未設定でも、キーワードベースのヒューリスティックで動作します）
2. **検索**: 経産省 **gBizINFO API**（無料・商用利用可）で、都道府県 × 社名キーワード（工務店・建設・
   不動産・住宅…）で母集団を集め、資本金の上限で絞り込みます
3. **詳細取得**（任意）: 各社の従業員数・業種・URLを取得して従業員数レンジで絞り込みます
4. **CSV出力**: 詳細CSV（会社名・所在地・資本金・従業員数・業種・URL）と、telepy一括架電用CSV
   （`phone_number, company_name`）を出力します

### 検索モード

リスト作成の検索元は複数から選べます。**外部の有料APIを使わない（従量課金ゼロ）構成**を基本にしています。

| モード | 説明 | 準備 | 従量課金 |
|---|---|---|---|
| **Web自動探索** | **条件に合う企業の公開HPをWebから自動で探してリスト化**（既定）。電話番号も取れる | なし（任意で検索APIキー） | ゼロ（DuckDuckGo） |
| **自前データ＋無料エンリッチ** | **国税庁の全件データ（無料）**で母集団を作り、無料Web検索でHP・電話番号を補完 | 国税庁CSVを一度取込 | ゼロ |
| **gBizINFO 自動巡回bot** | gBizINFOを巡回し、資本金・従業員数で厳密に絞る | APIトークン | ゼロ（無料API） |
| **ローカルCSV** | **PC内のCSVだけで検索**。`data/` にCSVを置くだけ | CSVを1つ置く | ゼロ |
| **デモ** | サンプルデータで画面確認 | なし | ゼロ |

> **設計方針**: 自前で解決できる部分（母集団・検索・抽出・エンリッチ）は全部ローカルで完結させ、
> 外部の有料AI（依頼文の高度な解釈など）は「無くても動く」任意オプションに留めています。
> そのぶんデータ容量やPC負荷は大きくなりますが、1リストあたりの外部コストは基本ゼロです。

#### Web自動探索（条件に合うHPを探してリスト化）

依頼文の条件（業種・地域）から検索クエリを自動生成し、Webを検索して条件に合う企業の
**公開ホームページ**を見つけ、各HPから **会社名・電話番号・住所** を抽出してリスト化します。
目標件数に達するか、検索クエリを使い切るまで探し続けます。CSVもトークンも不要です。

- **電話番号が取れる**のが強み（gBizINFOには無い）。架電用CSVにそのまま流せます
- 会社概要ページがあれば **資本金・従業員数** もベストエフォートで拾います
  （HPに記載が無い会社は「不明」として含めます。従業員数で厳密に絞りたいときは
  「従業員数不明を含める」を外す）
- 既定は **DuckDuckGo**（キー不要）で検索します。大量・高速に回したい場合は、設定画面の
  **検索APIキー**（[Serper.dev](https://serper.dev/) 等の無料枠）を登録するとより安定します
- ⚠ 検索エンジンや各サイトの利用規約・robots.txtを尊重し、常識的なアクセス頻度で使ってください
- ⚠ **純ブラウザ（GitHub Pages）単体ではWeb探索はできません**（CORS）。`python main.py` の
  ローカル版で動作します

「自動」にすると、`data/` にCSVがあればローカル、無ければgBizINFO、どちらも無ければデモを使います。

#### 自前データ＋無料エンリッチ（従量課金ゼロで社名→HP・電話番号）

「自前で作れるところは全部自前で」を実現するモードです。外部の有料APIを一切使わずに、
**① 無料の企業母集団 → ② 条件で絞り込み → ③ 無料Web検索でHP・電話番号を補完** まで一気通貫でやります。

1. **母集団を用意（無料）**: 国税庁「法人番号公表サイト」の全件データ（ダウンロード無料・トークン不要・
   全国約500万法人）を [`corp_importer.py`](corp_importer.py) で telepy 形式CSVに変換します。

   ```bash
   # 例: 一都三県だけ抽出して data/companies.csv に変換
   python corp_importer.py path/to/nta_zenken.zip --pref 東京都,神奈川県,千葉県,埼玉県
   ```

   - 入手先: <https://www.houjin-bangou.nta.go.jp/download/zenken/>（全国版 or 都道府県別、zip/csvどちらでも可）
   - 国税庁データは **社名＋所在地＋郵便番号のみ**（電話番号・業種・資本金・従業員数は含まない）
   - `--pref` で都道府県を絞ると、ファイルが小さくなり検索も速くなります

2. **絞り込み＋エンリッチ**: 検索モードを **「自前データ＋無料エンリッチ」** にして実行すると、
   母集団を社名キーワード（工務店・不動産など）×地域で絞り、各社を **無料のWeb検索（DuckDuckGo）** で
   調べて **公式HP・電話番号** を補完します。社名が一致したサイトだけを採用するので誤ヒットを抑えます。

- **1円もかけずに** 「社名＋所在地＋HP＋電話番号」のリストが作れます（PCの負荷と時間はかかります）
- 従業員数・資本金はHPの会社概要に記載がある場合のみ取得（無い会社は不明のまま含めます）
- ⚠ このモードも `python main.py` のローカル版で動作します（純ブラウザ単体はCORSで不可）

#### gBizINFO 自動巡回bot（1000件まで止まらない）

依頼文の条件を入れて実行すると、gBizINFOを **都道府県 × 社名キーワード × ページ** の全組み合わせで
自動巡回し、**目標件数に達するまで**条件（業種＝社名キーワード、都道府県、資本金、従業員数）に合う
企業を集め続けます。CSVを用意する必要はありません。

- ブラウザ画面に「探索中 N / 1000 社」とライブ表示されます
- 目標に到達したら停止。到達前に**該当が尽きた場合は、集められた分だけ**で終了し「これ以上見つからない」旨を表示します
- 「従業員数を確認して絞る（詳細取得）」を有効にすると各社の従業員数・業種・URLを取得して厳密に絞ります
  （精度は上がりますが、1社ずつ問い合わせるため時間がかかります）
- gBizINFOは小規模企業の従業員数が欠損しがちなため、件数確保には「従業員数不明も含める」を推奨
- ⚠ **純ブラウザ（GitHub Pages）単体ではこの自動巡回はできません**（CORS制約）。`python main.py` で
  起動したローカル版でのみ動作します

#### ローカルCSV検索（おすすめ・APIを毎回叩かない）

`data/` フォルダにCSVを置くと、**毎回APIを呼ばずPCの中だけ**で検索が完結します。
gBizINFOの一括ダウンロードCSV（約1.7GB・資本金/従業員数/業種入り）を一度落として置くのが王道です。
巨大ファイルでも1行ずつ処理するのでメモリを圧迫しません。列名は自動判別します。

- データの入手先・対応する列名は [`data/README.md`](data/README.md) を参照
- 同梱の `data/sample_companies.csv` ですぐ動作を試せます
- **電話番号入りのCSVを置けば、架電用CSVにも電話番号がそのまま入ります**

### 使い方

1. `python main.py` で起動し、ブラウザで http://localhost:8000/ を開く
2. 検索モードを選ぶ
   - **gBizINFO 自動巡回bot（既定）**: 設定画面で **gBizINFO APIトークン** を登録
     （[Web API利用申請](https://info.gbiz.go.jp/hojin/various_registration/form)で無料発行・商用可）。
     登録したら「リスト作成」画面の **「gBizINFO 接続テスト」** ボタンで疎通を確認できます
   - **ローカルCSV**: `data/` にCSVを置く（[`data/README.md`](data/README.md) 参照）
3. 依頼文を貼り「条件を読み取る」→ 内容を確認して「リストを作成」→ 目標件数まで自動で埋まっていきます
4. できたCSVをダウンロード。架電用CSVはそのまま架電管理のCSV一括架電に読み込めます

> どちらも未設定でも「デモ」モードで画面の動作を確認できます。

**うまく動かないとき**
- 「gBizINFO 接続テスト」で結果を確認してください。`❌ トークンが未設定/無効` と出たら、
  設定画面のgBizINFOトークンを見直してください（自動巡回botはトークン必須です）。
- 自動巡回botで結果が0件のまま止まった場合、ジョブがエラー理由（トークン未設定・通信不可など）を返します。
- トークンをすぐ用意できない場合は、検索モードを「ローカルCSV」にして `data/` のCSVから検索できます。

### データソースの注意点

- **従業員数**: gBizINFOの従業員数は行政手続データ由来のため、従業員10-20名規模の中小企業では
  欠損（不明）が多いです。件数を確保するため「従業員数不明を含める」を既定でオンにしています
  （確実に確認できた会社だけにしたい場合はオフに）
- **電話番号**: gBizINFOに電話番号は含まれません。架電用CSVの電話番号欄は空欄で出力されるため、
  別途エンリッチ（Web検索や他ソース）で補完してください
- **業種**: gBizINFO v2は業種での検索パラメータを持たないため、社名キーワードで母集団を集める方式です。
  「工務店」「不動産」など業種名が社名に含まれやすい業界と特に相性が良い設計です

### API

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/list/parse` | 依頼文を検索条件に構造化 |
| POST | `/api/list/build` | リスト作成ジョブを非同期で開始（`mode`=auto/web/local_web/local/api/demo、`job_id`を返す） |
| GET | `/api/list/jobs/{job_id}` | ジョブの進捗・結果（プレビュー）を取得 |
| GET | `/api/list/jobs/{job_id}/export?fmt=detail\|call` | 完成リストをCSVでダウンロード |
| GET | `/api/list/local-status` | ローカルCSV（PC内検索用）の設置状況を取得 |

## セットアップ手順

### 1. リポジトリのクローンと依存パッケージのインストール

```bash
cd teleapo-ai
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` ファイルを編集し、各サービスのAPIキーを設定してください。

| 環境変数 | 説明 | 取得先 |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | TwilioアカウントSID | [Twilio Console](https://console.twilio.com/) |
| `TWILIO_AUTH_TOKEN` | Twilio認証トークン | Twilio Console |
| `TWILIO_PHONE_NUMBER` | Twilio発信用電話番号 | Twilio Console（番号購入が必要） |
| `DEEPGRAM_API_KEY` | Deepgram APIキー | [Deepgram Console](https://console.deepgram.com/) |
| `ELEVENLABS_API_KEY` | ElevenLabs APIキー | [ElevenLabs](https://elevenlabs.io/) |
| `ELEVENLABS_VOICE_ID` | ElevenLabs音声ID | ElevenLabs（日本語対応音声を選択） |
| `ANTHROPIC_API_KEY` | Anthropic APIキー | [Anthropic Console](https://console.anthropic.com/) |
| `FIREBASE_CREDENTIALS_PATH` | Firebase認証JSONのパス | [Firebase Console](https://console.firebase.google.com/) |
| `FIREBASE_PROJECT_ID` | FirebaseプロジェクトID | Firebase Console |
| `SLACK_WEBHOOK_URL` | Slack Webhook URL | [Slack API](https://api.slack.com/messaging/webhooks) |
| `GBIZINFO_API_TOKEN` | gBizINFO APIトークン（リスト作成機能用・無料） | [gBizINFO API利用申請](https://info.gbiz.go.jp/hojin/various_registration/form) |

### 3. Firebaseの設定

1. [Firebase Console](https://console.firebase.google.com/) でプロジェクトを作成
2. **Firestore Database** を作成（本番モード）
3. **プロジェクトの設定** → **サービスアカウント** → **新しい秘密鍵の生成**
4. ダウンロードしたJSONファイルをプロジェクトルートに `firebase-credentials.json` として保存

Firestoreには `call_logs` コレクションが自動作成されます（テーブル定義不要）。

### 4. ngrokの設定（ローカル開発用）

Twilioからのwebhookを受け取るために、ngrokでトンネルを作成します。

```bash
ngrok http 8000
```

表示されたURLを `.env` に `BASE_URL` として追加してください。

```
BASE_URL=https://xxxx-xxxx.ngrok.io
```

### 5. サーバーの起動

```bash
python main.py
```

サーバーが `http://localhost:8000` で起動します。

## 使い方

### 単体架電

```bash
curl -X POST "http://localhost:8000/call/initiate" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "phone_number=+819012345678"
```

### CSV一括架電

CSVファイル形式:
```csv
phone_number,company_name
+819012345678,株式会社テスト
+819087654321,サンプル合同会社
```

```bash
curl -X POST "http://localhost:8000/call/batch" \
  -F "file=@call_list.csv"
```

### アクティブセッション確認

```bash
curl http://localhost:8000/sessions
```

### ヘルスチェック

```bash
curl http://localhost:8000/health
```

## クライアントスクリプトのカスタマイズ

`scripts/` ディレクトリにYAMLファイルを作成して、クライアントごとのスクリプトを定義できます。

```yaml
client_name: "株式会社○○"
product: "商材名"
target: "ターゲット役職"
greeting: "挨拶文..."
pitch: "商材説明文..."
objection_responses:
  - trigger: "トリガーワード"
    response: "返答文..."
closing: "クロージング文..."
farewell: "終話文..."
```

架電時にスクリプトパスを指定:
```bash
curl -X POST "http://localhost:8000/call/initiate" \
  -d "phone_number=+819012345678&script_path=scripts/custom_client.yaml"
```

## APIドキュメント

サーバー起動後、以下にアクセスするとSwagger UIが利用できます。

```
http://localhost:8000/docs
```
