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

### 使い方

1. 設定画面で **gBizINFO APIトークン** を登録（[Web API利用申請](https://info.gbiz.go.jp/hojin/various_registration/form)で無料発行・商用可）
2. リスト作成タブで依頼文を貼り「条件を読み取る」→ 内容を確認して「リストを作成」
3. できたCSVをダウンロード。架電用CSVはそのまま架電管理のCSV一括架電に読み込めます

> トークン未設定でも「デモデータで試す」で画面の動作を確認できます。

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
| POST | `/api/list/build` | リスト作成ジョブを非同期で開始（`job_id`を返す） |
| GET | `/api/list/jobs/{job_id}` | ジョブの進捗・結果（プレビュー）を取得 |
| GET | `/api/list/jobs/{job_id}/export?fmt=detail\|call` | 完成リストをCSVでダウンロード |

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
