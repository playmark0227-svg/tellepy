# telepy — 作業メモ

## 応答のきまり

**返答の最後に、必ず公開URLを載せること。**（利用者からの依頼）

- アプリ本体: https://playmark0227-svg.github.io/tellepy/list.html
- 紹介ページ: https://playmark0227-svg.github.io/tellepy/

変更を `main` にマージした回はもちろん、コードを触っていない回（質問への回答だけ、
調査だけ）でも省略しない。

## この repo のかたち

| 場所 | 中身 |
|---|---|
| `docs/list.html` | ブラウザ版アプリ（単一の自己完結HTML。GitHub Pages で公開） |
| `docs/index.html` | 紹介ページ |
| `main.py` ほか | ローカル版（`python main.py`）。Twilio 架電・管理画面・API |
| `list_builder.py` | 検索条件・絞り込み・CSV出力の中核 |
| `web_finder.py` | 無料のWeb探索（DuckDuckGo）とAIフォールバック |

### docs/list.html を触るときの約束

- **純データ層（`var PREFECTURE_CODES` から `var LB = {` の直前まで）は変更しない。**
  CSVストリーミングパーサ・文字コード判定・絞り込み・費用の上限ガードが入っている。
  画面を作り直すときも、この範囲は1文字も動かさずに載せ替える。
- 外部CDN・外部フォントを足さない（「どこにも送信しません」と画面に書いてあるため）。
- 画面本体の地の文は増やさない（目安120字以内）。説明は `UI.info()` の中に置く。
- 「依頼文の読み取り」は辞書と正規表現。**AIと呼ばない。**
  AIと書いてよいのは Anthropic API を実際に叩く箇所だけ。

## テスト

```bash
python test_list_builder.py test_web_finder.py  # ではなく個別に実行する
python test_list_builder.py
python test_web_finder.py
python test_corp_importer.py
python test_nta_updater.py
python test_api_auth.py
node test_docs_list.mjs        # ブラウザ版のロジック（Playwright）
node test_docs_list_ui.mjs     # ブラウザ版の画面の約束（Playwright）
```

`test_docs_list_ui.mjs` は見た目ではなく「言っていることとやっていることが合うか」を
検査している（見本データを本物として出力できないか、押す前に金額が出るか、
読み取りをAIと呼んでいないか等）。文言を変えるときはここが落ちないか確認する。
