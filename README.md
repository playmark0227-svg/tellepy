# telepy（テレパイ）- テレアポ代行AIシステム

AIが自動で架電し、アポイントを取得したら人間にハンドオフするテレアポ代行サービスです。

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
