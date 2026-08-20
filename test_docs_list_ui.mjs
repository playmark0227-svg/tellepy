/* ブラウザ版（docs/list.html）を実際に操作して、画面の約束が守られているか検証する。
 *
 *   node test_docs_list_ui.mjs
 *
 * ここで見ているのは見た目ではなく「言っていることと、やっていることが合うか」。
 *   - 読み取りをAIと呼んでいないか（実際はルール解析）
 *   - 効かない条件を、走らせる前に宣告しているか
 *   - 電話番号が無いリストを「できました」と言い切っていないか
 *   - 架空の見本データが本物として出力できてしまわないか
 *   - 有料の工程で、押す前に金額が出ているか
 * Playwright（Chromium）が必要。無い環境ではスキップされる。
 */
import { createServer } from 'http';
import { readFile, mkdtemp, writeFile } from 'fs/promises';
import { tmpdir } from 'os';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

const DOCS = join(dirname(fileURLToPath(import.meta.url)), 'docs');
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript',
                '.png': 'image/png', '.svg': 'image/svg+xml' };

// docs/ を配るだけの小さなサーバー（外部依存を増やさないため自前で立てる）
const server = createServer(async (req, res) => {
  const path = resolve(join(DOCS, decodeURIComponent(req.url.split('?')[0])));
  if (!path.startsWith(DOCS)) { res.writeHead(403).end(); return; }
  try {
    const body = await readFile(path);
    const ext = path.slice(path.lastIndexOf('.'));
    res.writeHead(200, { 'content-type': TYPES[ext] || 'application/octet-stream' }).end(body);
  } catch { res.writeHead(404).end('not found'); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const BASE = 'http://127.0.0.1:' + server.address().port;

// Playwright はグローバル導入・ローカル導入のどちらでも拾えるようにする
let chromium = null;
for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.js']) {
  try {
    const mod = await import(spec);
    chromium = (mod.chromium || mod.default?.chromium) ?? null;
    if (chromium) break;
  } catch { /* 次の候補へ */ }
}
if (!chromium) {
  console.log('Playwright が見つからないためスキップします（このテストは任意）');
  server.close();
  process.exit(0);
}
const EXE = process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium';


const B = await mkdtemp(join(tmpdir(), 'telepy-ui-'));

// 国税庁形式（ヘッダ無し30列）のテストデータを作る
const names = ['まごころ工務店', 'ハマノ不動産', 'さくら建設', 'むさし住宅', '大栄ホーム',
               '丸和工務店', '青葉建築', '第一リフォーム', '港土木', '緑ハウス'];
const prefs = [['東京都', '世田谷区'], ['神奈川県', '横浜市'], ['千葉県', '船橋市'], ['埼玉県', '川口市']];
const rows = [];
for (let i = 0; i < 400; i++) {
  const r = new Array(30).fill('');
  const p = prefs[i % 4];
  r[1] = String(1010001000000 + i);
  r[6] = '株式会社' + names[i % names.length] + i;
  r[8] = '301'; r[9] = p[0]; r[10] = p[1]; r[11] = `${i}-1-1`;
  r[15] = '1550031'; r[23] = '1'; r[29] = '0';
  rows.push(r.join(','));
}
await writeFile(join(B, 'nta_test.csv'), rows.join('\n') + '\n');
await writeFile(join(B, 'dummy.zip'), Buffer.from('PKfake'));
const browser = await chromium.launch(EXE ? { executablePath: EXE } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
const errors = [];
page.on('pageerror', e => errors.push(String(e)));
const ok = [];
const check = (n, c, d) => { if (!c) throw new Error(`${n} 失敗: ${d}`); ok.push(n); };

await page.goto(BASE + '/list.html');
await page.waitForTimeout(600);

// まずスクリプトが生きているかを見る。文法エラーを、あとの検査の
// 分かりにくいタイムアウトとしてではなく、その場で報告させる。
if (errors.length) throw new Error('読み込み時点でJSエラー: ' + errors.join(' / '));
const alive = await page.evaluate(() => [typeof LB, typeof TP, typeof CX].join(','));
check('スクリプトが最後まで読み込める', alive === 'object,object,object', alive);

// ① 起動画面: CSVもAPIキーも要求しない
const firstView = await page.textContent('#feed');
check('起動画面が依頼文から始まる', /お客様からの依頼文/.test(firstView), '');
check('起動時にAPIキーを要求しない', !/sk-ant/.test(await page.textContent('#tp-hello')), '');
await page.waitForFunction(
  () => !/確認しています/.test(document.getElementById('tp-seed-desc').textContent), null, { timeout: 8000 });
check('内蔵データの状態を名乗る', /内蔵データはまだ入っていません|内蔵済み/.test(await page.textContent('#tp-seed-desc')),
  await page.textContent('#tp-seed-desc'));

// ② 読み取り: 実データのトレースが出る
await page.fill('#lb-inquiry', '工務店、不動産のリスト作成をお願いします。従業員数10-20名、資本金1000万円以下、一都三県で1000件ほど。');
await page.click('text=この依頼文で条件を読み取る');
await page.waitForSelector('#lb-criteria-card:not(.hidden)', { timeout: 8000 });
await page.waitForTimeout(500);
const trace = await page.textContent('#tp-trace');
check('読み取り結果を実データで実況', /一都三県|東京都/.test(trace) && /1,000件/.test(trace), trace);
check('読み取りをAIと呼ばない', (await page.textContent('#tp-badge-parse')) === 'ルール解析',
  await page.textContent('#tp-badge-parse'));
check('社名キーワードがチップで見える', (await page.$$('#tp-kw-chips .kw-chip')).length >= 5, '');

// ③ データが無くても「どこから探しますか」とは聞かない。探し方を自分で出す。
await page.waitForSelector('#tp-go:not(.hidden)', { timeout: 8000 });
check('データが無くても探し先を質問しない', !(await page.isVisible('#tp-data-msg')), '');
const plan = await page.textContent('#tp-go-text');
check('代わりに探し方を提案する', /AIにWebから探させる|AIがWebを検索/.test(plan), plan);
check('無料の道も同時に示す', /無料/.test(plan + await page.textContent('#tp-go-alt')), plan);
check('ボタンが探索を指す', /AIに探させる/.test(await page.textContent('#tp-go-label')),
  await page.textContent('#tp-go-label'));

// ④ zipが開けないときは従来どおり案内（偽zipで確認）
await page.setInputFiles('#lb-file', B + '/dummy.zip');
await page.waitForTimeout(400);
const zl = await page.textContent('#lb-file-label');
check('開けないzipは正直に案内', /zip/.test(zl) && /解凍/.test(zl), zl);

// ⑤ 実データを渡すと、走る前に「効かない条件」を宣告する
await page.setInputFiles('#lb-file', B + '/nta_test.csv');
await page.waitForSelector('#tp-preflight-wrap:not(.hidden)', { timeout: 8000 });
await page.waitForTimeout(300);
const pf = await page.textContent('#tp-preflight');
check('資本金が効かないことを走る前に言う', /資本金[\s\S]*?列がありません/.test(pf), pf);
check('従業員数が効かないことを走る前に言う', /従業員数[\s\S]*?列がありません/.test(pf), pf);
check('電話番号が無いことを走る前に言う', /電話番号[\s\S]*?入っていません/.test(pf), pf);
check('✗には必ず対処ボタンがある', (await page.$$('.pf-ng .btn')).length >= 2, '');
check('聞き返しが出る', await page.isVisible('#tp-ask'), '');
check('データを渡したら無料の探索に切り替わる',
  /この条件で探す/.test(await page.textContent('#tp-go-label')) &&
  /通信も課金もありません/.test(await page.textContent('#tp-go-text')),
  await page.textContent('#tp-go-label'));

// ⑥ 聞き返しに答えると条件が実際に変わる
await page.click('text=不明も含めて集める（おすすめ）');
await page.waitForTimeout(400);
check('答えがチェック状態に反映される', await page.isChecked('#lb-unknown'), '');

// ⑦ 実行 → 納品ボード
await page.click('#lb-run');
await page.waitForSelector('#lb-result-card:not(.hidden)', { timeout: 20000 });
await page.waitForTimeout(900);
const title = await page.textContent('#lb-result-title');
check('主役の数値が「架電できる社数」', /架電できる\s*0\s*\/\s*\d/.test(title.replace(/\s+/g, ' ')), title);
check('2ペインに分割される', (await page.getAttribute('#stage', 'class')).includes('has-board'), '');
check('架電用CSVは0件なら押せない', await page.isDisabled('#tp-dl-call'), '');
check('詳細CSVは押せる', !(await page.isDisabled('#tp-dl-detail')), '');
const verdict = await page.textContent('#tp-verdict-body');
check('半製品であることを自分から言う', /1件も架電できません/.test(verdict), verdict);
const quality = await page.textContent('#lb-note');
check('分かっていないことを列挙する', /資本金の条件は適用していません/.test(quality), quality);
check('AI補完カードが出る', await page.isVisible('#lb-ai-card'), '');
const quote = await page.textContent('#tp-quote-amt');
check('押す前に金額が出る', /^≒ ¥[\d,]+$/.test(quote.trim()), quote);
await page.waitForTimeout(700);
check('済んだ工程が畳まれる', await page.isVisible('#tp-compact') && !(await page.isVisible('#tp-intro')), '');
check('畳んでも条件が一目で分かる', /工務店/.test(await page.textContent('#tp-compact-desc')),
  await page.textContent('#tp-compact-desc'));
const headTop = await page.evaluate(() => Math.round(document.querySelector('.board-head').getBoundingClientRect().top));
check('リストの見出し（架電できる件数）が画面内に残る', headTop >= 0 && headTop < 200, 'top=' + headTop);

// ⑧ 選定理由が1社ごとに開く
await page.click('tr.row-main');
await page.waitForTimeout(300);
check('行クリックで根拠が開く', (await page.$$('tr.row-why.is-open')).length === 1, '');
const why = await page.textContent('tr.row-why.is-open');
check('根拠が実データで書かれる', /社名に「/.test(why) && /電話番号 未取得/.test(why), why);

// ⑨ 「このリストの作り方」
await page.click('#tp-recipe summary');
await page.waitForTimeout(200);
const recipe = await page.textContent('#tp-recipe-body');
check('AIを使っていないことを明記', /AIを使った箇所：ありません/.test(recipe), recipe);
check('走査行数が実測で入る', /400行を読み/.test(recipe), recipe);

// ⑨-2 該当0件のときは、専用の案内を初回から出す（無言の空表にしない）
await page.click('text=条件を変える');
await page.waitForTimeout(400);
// 社名キーワードの生入力は「詳細設定」の中にあるので開いてから触る
await page.evaluate(() => { document.querySelector('#lb-criteria-card details.adv').open = true; });
await page.fill('#lb-keywords', '絶対に一致しない社名キーワード');
await page.fill('#lb-industries', '');
await page.click('#lb-run');
await page.waitForSelector('#lb-result-card:not(.hidden)', { timeout: 20000 });
await page.waitForTimeout(600);
check('0件のときは専用の案内が出る', await page.isVisible('#lb-empty'), '');
check('0件なら詳細CSVも押せない', await page.isDisabled('#tp-dl-detail'), '');
await page.evaluate(() => LB.download('call'));
await page.waitForTimeout(300);
check('電話番号0件の架電用CSVは理由つきで止める',
  /先にリストを作成してください|電話番号がまだ1件もありません/.test(await page.textContent('#toasts')),
  await page.textContent('#toasts'));
// 0件のときは工程を畳まない（条件を直す画面を出したままにする）
check('0件のときは条件カードを開いたままにする', await page.isVisible('#lb-criteria-card'), '');
await page.fill('#lb-industries', '工務店, 不動産');
await page.fill('#lb-keywords', '');

// ⑩ 見本モード: 印が付き、ダウンロードが封鎖される
await page.evaluate(() => TP.expand(true));   // 「依頼文から やり直す」と同じ
await page.waitForTimeout(600);
check('畳んだ工程を開き直せる', await page.isVisible('#tp-intro'), '');
await page.click('text=同梱サンプル（架空の12社）で動作だけ見る');
await page.waitForTimeout(700);
await page.click('#lb-run');
await page.waitForSelector('#tp-sample-band:not(.hidden)', { timeout: 15000 });
await page.waitForTimeout(600);
check('見本には常時の警告帯が出る', await page.isVisible('#tp-sample-band'), '');
check('見本は詳細CSVも落とせない', await page.isDisabled('#tp-dl-detail'), '');
check('見本は架電用CSVも落とせない', await page.isDisabled('#tp-dl-call'), '');
check('見本の行に印が付く', (await page.$$('.why.is-sample')).length > 0, '');
await page.evaluate(() => LB.download('detail'));
await page.waitForTimeout(300);
check('見本のダウンロードを試みたら理由を出す',
  /見本はダウンロードできません/.test(await page.textContent('#toasts')), await page.textContent('#toasts'));

// ⑩-2 AIによる探索: Anthropicの応答を差し替えて、判定と組み立てだけを確かめる
await page.evaluate(() => TP.expand(true));
await page.waitForTimeout(400);
const discovery = await page.evaluate(async () => {
  // 実際のAPIは叩かず、応答だけ差し替える（課金しないでロジックを試す）
  const real = window.fetch;
  let round = 0;
  const reply = (companies) => ({
    ok: true,
    json: async () => ({
      content: [{ type: 'text', text: '見つかりました。\n' + JSON.stringify({ companies }) }],
      usage: { input_tokens: 5000, output_tokens: 800, server_tool_use: { web_search_requests: 3 } }
    })
  });
  window.fetch = async (url, opt) => {
    if (String(url).indexOf('api.anthropic.com') === -1) return real(url, opt);
    round++;
    if (round === 1) return reply([
      // 業種名を社名に含まない会社（落としてはいけない）
      { name: '鮨いち', location: '大阪府大阪市北区1-1', prefecture: '大阪府',
        phone_number: '06-1111-2222', company_url: 'https://sushi-ichi.example.jp',
        source_url: 'https://sushi-ichi.example.jp/about' },
      // 出どころが無い（実在を確かめられないので捨てる）
      { name: '出どころ不明亭', location: '大阪府大阪市', prefecture: '大阪府',
        phone_number: '06-9999-9999', company_url: '', source_url: '' },
      // エリア外（条件に合わないので捨てる）
      { name: '東京らーめん', location: '東京都新宿区', prefecture: '東京都',
        phone_number: '03-1111-1111', company_url: 'https://ramen.example.jp',
        source_url: 'https://ramen.example.jp' },
      { name: '株式会社味の里', location: '大阪府堺市2-2', prefecture: '大阪府',
        phone_number: '', company_url: 'https://ajinosato.example.jp',
        source_url: 'https://ajinosato.example.jp' }
    ]);
    if (round === 2) return reply([
      // 1回目と同じ会社（法人格の表記ゆれ込み。重複として落とす）
      { name: '鮨いち', location: '大阪府大阪市北区1-1', prefecture: '大阪府',
        phone_number: '06-1111-2222', company_url: 'https://sushi-ichi.example.jp',
        source_url: 'https://sushi-ichi.example.jp' },
      { name: '有限会社 味の里', location: '大阪府堺市2-2', prefecture: '大阪府',
        phone_number: '', company_url: 'https://ajinosato.example.jp',
        source_url: 'https://ajinosato.example.jp' }
    ]);
    return reply([]);   // 以降は新規なし → 打ち切りへ
  };

  document.getElementById('lb-ai-key').value = 'sk-ant-test-not-a-real-key';
  document.getElementById('lb-industries').value = '飲食店';
  document.getElementById('lb-keywords').value = '';
  document.getElementById('lb-prefectures').value = '大阪府';
  document.getElementById('lb-count').value = '50';
  document.getElementById('lb-ai-budget').value = '0';
  LB._files = null; LB._aiCalls = 0; LB._aiIn = 0; LB._aiOut = 0; LB._aiSearches = 0;
  await LB.discover();
  window.fetch = real;
  return {
    names: LB.companies.map(c => c.name),
    reasons: [...new Set(LB.companies.map(c => c.match_reason))],
    calls: LB._aiCalls
  };
});
check('業種名を社名に含まない会社を落とさない', discovery.names.includes('鮨いち'),
  JSON.stringify(discovery));
check('出どころを示せない会社は採用しない', !discovery.names.includes('出どころ不明亭'),
  JSON.stringify(discovery));
check('エリア外は採用しない', !discovery.names.includes('東京らーめん'), JSON.stringify(discovery));
check('表記ゆれの重複をまとめる', discovery.names.length === 2, JSON.stringify(discovery));
check('新しい会社が出なくなったら止める', discovery.calls <= 4, 'calls=' + discovery.calls);
check('探索由来だと分かる印を付ける',
  discovery.reasons.length === 1 && /探索/.test(discovery.reasons[0]), JSON.stringify(discovery.reasons));
await page.waitForTimeout(600);
check('探索結果にも納品ボードが出る', await page.isVisible('#lb-result-card'), '');
check('探索は自動判定だと結果に明記', /AIがWebを検索して見つけた会社/.test(await page.textContent('#lb-note')),
  await page.textContent('#lb-note'));
const dRecipe = await page.textContent('#tp-recipe-body');
check('作り方に「手元の名簿は使っていない」と書く', /手元の名簿は使っていません/.test(dRecipe), dRecipe);
check('探索行のチップが「AIが探索」', (await page.$$('.why.is-ai')).length > 0, '');

// ⑩-3 辞書に無い業種（飲食店）でも、依頼文をAIに渡して探せる
const unlisted = await page.evaluate(async () => {
  const real = window.fetch;
  let sent = null;
  window.fetch = async (url, opt) => {
    if (String(url).indexOf('api.anthropic.com') === -1) return real(url, opt);
    sent = JSON.parse(opt.body);
    return { ok: true, json: async () => ({
      content: [{ type: 'text', text: JSON.stringify({ companies: [] }) }],
      usage: { input_tokens: 100, output_tokens: 10, server_tool_use: { web_search_requests: 1 } } }) };
  };
  document.getElementById('lb-inquiry').value = '美容室のリストを大阪府で50件お願いします。';
  LB.parse();
  await new Promise(r => setTimeout(r, 1200));
  const c = LB.collectCriteria();
  await LB.discover();
  window.fetch = real;
  return {
    industriesEmpty: c.industries.length === 0 && c.name_keywords.length === 0,
    promptHasInquiry: /美容室/.test(sent ? sent.messages[0].content : ''),
    planLabel: document.getElementById('tp-go-label').textContent
  };
});
check('辞書に無い業種は条件が空になる（前提の確認）', unlisted.industriesEmpty, JSON.stringify(unlisted));
check('それでも依頼文をAIに渡して探せる', unlisted.promptHasInquiry, JSON.stringify(unlisted));
check('その場合ボタンもAI探索を指す', /AIに探させる/.test(unlisted.planLabel), unlisted.planLabel);

// ⑪ 料金シート
await page.click('#tp-cost-chip');
await page.waitForTimeout(400);
const sheet = await page.textContent('#tp-sheet-body');
check('無料と有料の境界が画面内で分かる', /無料/.test(sheet) && /従量/.test(sheet) && /python main\.py/.test(sheet), '');
await page.click('[data-tab="source"]');
await page.waitForTimeout(300);
check('AIでない処理をAIと呼ばない説明がある',
  /AIではありません/.test(await page.textContent('#tp-sheet-body')), '');

// ⑫ ダークテーマ
await page.keyboard.press('Escape');
await page.waitForTimeout(200);
await page.click('#theme-toggle');
await page.waitForTimeout(500);
check('ダークテーマに切り替わる', (await page.getAttribute('html', 'data-theme')) === 'dark', '');

if (errors.length) throw new Error('page errors: ' + errors.join(' / '));
ok.forEach(n => console.log('OK ' + n));
console.log(`\nALL ${ok.length} FLOW CHECKS PASSED`);
await browser.close();
server.close();
