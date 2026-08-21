/* ブラウザ版（docs/list.html）を実際に操作して、画面の約束が守られているか検証する。
 *
 *   node test_docs_list_ui.mjs
 *
 * 画面は「左に条件・右に結果」の1画面。見た目ではなく、
 * 言っていることとやっていることが合うかを見る。
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
// 国税庁形式（ヘッダ無し30列）のテストデータ
const names = ['まごころ工務店','ハマノ不動産','さくら建設','むさし住宅','大栄ホーム',
               '丸和工務店','青葉建築','第一リフォーム','港土木','緑ハウス'];
const prefs = [['東京都','世田谷区北沢'],['神奈川県','横浜市港北区'],['千葉県','船橋市本町'],['埼玉県','川口市栄町']];
const rows = [];
for (let i = 0; i < 400; i++) {
  const r = new Array(30).fill('');
  const p = prefs[i % 4];
  r[1] = String(1010001000000 + i);
  r[6] = '株式会社' + names[i % names.length] + i;
  r[8] = '301'; r[9] = p[0]; r[10] = p[1]; r[11] = `${(i%40)+1}-${(i%9)+1}`;
  r[15] = '1550031'; r[23] = '1'; r[29] = '0';
  rows.push(r.join(','));
}
await writeFile(join(B, 'nta_test.csv'), rows.join('\n') + '\n');


// 国税庁形式（ヘッダ無し30列）のテストデータを作る
const browser = await chromium.launch(EXE ? { executablePath: EXE } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors=[]; page.on('pageerror', e=>errors.push(String(e)));
const ok=[]; const check=(n,c,d)=>{ if(!c) throw new Error(n+' 失敗: '+d); ok.push(n); };
await page.goto(BASE + '/list.html'); await page.waitForTimeout(700);
if (errors.length) throw new Error('起動時JSエラー: '+errors.join(' / '));

// 初期
check('起動時に押せないボタンが目立たない',
  (await page.getAttribute('#tp-dl-call','class')).includes('btn-line'),
  await page.getAttribute('#tp-dl-call','class'));
check('条件が最初から全部見えている',
  await page.isVisible('#area-list') && await page.isVisible('#lb-count') && await page.isVisible('#lb-run'), '');
check('名簿を持っていなくても探せる状態で始まる',
  /Webから探す/.test(await page.textContent('#lb-run')), await page.textContent('#lb-run'));
check('押す前に金額が出る', /≒ ¥[\d,]+/.test(await page.textContent('#run-note')),
  await page.textContent('#run-note'));
check('名簿は要らないと明記', /名簿不要/.test(await page.textContent('#method-hint')),
  await page.textContent('#method-hint'));
check('データ元の行は出さない', !(await page.isVisible('#src-row')), '');
check('よく使う条件が最初から並ぶ', (await page.$$('#tp-presets .preset')).length >= 3, '');
// 「読み取りはAIではない」を否定文ではなく計器で示す
check('計器がAI0回から始まる', /AI\s*0\s*回/.test((await page.textContent('#tp-meter')).replace(/\s+/g,' ')),
  await page.textContent('#tp-meter'));
check('規模はAIへの希望として伝えると書く',
  /希望として伝達/.test(await page.textContent('#note-emp')), await page.textContent('#note-emp'));
check('規模の欄は塞がない', !(await page.isDisabled('#lb-emp-min')), '');

// 依頼文 → 条件（チップとチェックに反映されるか）
await page.fill('#lb-inquiry','工務店、不動産のリスト。従業員10-20名、資本金1000万円以下、一都三県で1000件');
await page.click('text=条件を読み取る'); await page.waitForTimeout(600);
check('業種がチップになる', (await page.$$('#tag-list .tag')).length === 2, '');
const checked = await page.$$eval('#area-list input:checked', a=>a.map(x=>x.value));
check('エリアがチェックに入る', checked.length===4 && checked.includes('東京都'), JSON.stringify(checked));
check('件数が入る', await page.inputValue('#lb-count')==='1000', await page.inputValue('#lb-count'));
check('依頼文を読んでも計器は0のまま',
  /AI\s*0\s*回/.test((await page.textContent('#tp-meter')).replace(/\s+/g,' ')),
  await page.textContent('#tp-meter'));
check('貼り付け欄が畳まれる', !(await page.getAttribute('#lb-inquiry','class')).includes('tall'), '');

// 名簿から探すに切り替えると、データ元の行が出る
await page.click('[data-m="local"]'); await page.waitForTimeout(300);
check('名簿に切り替えるとデータ元が出る', await page.isVisible('#src-row'), '');
check('名簿は無料だと書く', /無料/.test(await page.textContent('#run-note')),
  await page.textContent('#run-note'));
check('実行ボタンに件数を入れない', !/\d/.test(await page.textContent('#lb-run')),
  await page.textContent('#lb-run'));

// データを渡す → 使えない条件が「その欄」に出る
await page.setInputFiles('#lb-file', B+'/nta_test.csv'); await page.waitForTimeout(1000);
check('従業員数の欄が無効になる', await page.isDisabled('#lb-emp-min'), '');
check('資本金の欄が無効になる', await page.isDisabled('#cap-sel'), '');
check('欄のすぐ横に理由が出る', /この列がありません/.test(await page.textContent('#note-emp')),
  await page.textContent('#note-emp'));
check('データ元が左下に出る', /nta_test/.test(await page.textContent('#lb-file-label')),
  await page.textContent('#lb-file-label'));
const cols = (await page.textContent('#tp-columns')).replace(/\s+/g,' ');
check('名簿が持つ列を記号と列名で示す',
  /✓ 社名/.test(cols) && /✕ 電話番号/.test(cols) && /✕ 資本金/.test(cols), cols);

// 探す
await page.click('#lb-run'); await page.waitForTimeout(2500);
check('件数が見出しに出る', /400/.test(await page.textContent('#lb-result-title')),
  await page.textContent('#lb-result-title'));
check('電話番号0が警告色で出る', (await page.$$('#lb-result-title .zero')).length===1, '');
check('架電用CSVは押せない', await page.isDisabled('#tp-dl-call'), '');
check('詳細CSVは押せる', !(await page.isDisabled('#tp-dl-detail')), '');
check('電話番号が無いことを脚に出す', /電話番号は元データに含まれません/.test(await page.textContent('#lb-note')),
  await page.textContent('#lb-note'));
check('資本金が効かなかったことも出す', /資本金の条件は使えませんでした/.test(await page.textContent('#lb-note')), '');
check('名簿だけで探せば計器は0のまま',
  /AI\s*0\s*回/.test((await page.textContent('#tp-meter')).replace(/\s+/g,' ')),
  await page.textContent('#tp-meter'));
check('電話番号を調べるボタンに件数と金額が載る',
  /\d+社 ≒¥[\d,]+/.test(await page.textContent('#btn-ai')), await page.textContent('#btn-ai'));

// 件数を変えたら走査せず即反映
const before = await page.$$eval('#lb-tbody tr', r=>r.length);
await page.fill('#lb-count','50'); await page.dispatchEvent('#lb-count','change'); await page.waitForTimeout(300);
const after = await page.$$eval('#lb-tbody tr', r=>r.length);
check('件数変更は走査せず即反映', before===300 && after===50, before+'→'+after);
check('その間ずっと結果が見えている', !(await page.isVisible('#lb-progress-card')), '');

// この時点ではAIを1回も使っていない。その状態の「作り方」を確かめる。
await page.evaluate(() => UI.info('recipe')); await page.waitForTimeout(300);
check('AI未使用なら0円と書く', /使っていません（0円）/.test(await page.textContent('#info-body')),
  await page.textContent('#info-body'));
check('読み取りをAIと呼ばない', /AIではありません/.test(await page.textContent('#info-body')), '');
await page.evaluate(() => UI.close('dlg-info')); await page.waitForTimeout(200);

// 見本モード
await page.click('#lb-count'); await page.fill('#lb-count','1000');
await page.evaluate(()=>LB.useSample()); await page.waitForTimeout(2500);
check('見本の帯が出る', await page.isVisible('#tp-sample-band'), '');
check('見本は両方落とせない',
  (await page.isDisabled('#tp-dl-detail')) && (await page.isDisabled('#tp-dl-call')), '');
check('見本の行に印が付く', (await page.$$('.src-dot.sample')).length>0, '');
await page.evaluate(()=>LB.download('detail')); await page.waitForTimeout(300);
check('見本DLは理由つきで止まる', /見本はダウンロードできません/.test(await page.textContent('#toasts')), '');

// ⑩-2 AIによる探索: Anthropicの応答を差し替えて、判定と組み立てだけを確かめる
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
  document.getElementById('lb-prefectures').value = '大阪府';
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
check('探索は自動判定だと結果に明記', /自動判定・未検証/.test(await page.textContent('#lb-note')),
  await page.textContent('#lb-note'));
await page.evaluate(() => UI.info('recipe'));
await page.waitForTimeout(300);
const dRecipe = await page.textContent('#info-body');
check('作り方の出所がAIのWeb検索になる', /AIによるWeb検索/.test(dRecipe), dRecipe);
await page.evaluate(() => UI.close('dlg-info'));
check('探索行に印が付く', (await page.$$('.src-dot.ai')).length > 0, '');

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
    planLabel: '—'
  };
});
check('辞書に無い業種は条件が空になる（前提の確認）', unlisted.industriesEmpty, JSON.stringify(unlisted));
check('それでも依頼文をAIに渡して探せる', unlisted.promptHasInquiry, JSON.stringify(unlisted));



// 主導線（左下のボタン）から、名簿なしでWebから探せるか
await page.evaluate(() => { LB._files = null; LB.companies = []; LB._pool = []; LB._lastOut = null;
  LB._aiCalls = 0; LB._aiIn = 0; LB._aiOut = 0; LB._aiSearches = 0; });
await page.click('[data-m="web"]'); await page.waitForTimeout(300);
const webRun = await page.evaluate(async () => {
  const real = window.fetch; let calls = 0;
  let sentBody = null;
  window.fetch = async (url, opt) => {
    if (String(url).indexOf('api.anthropic.com') === -1) return real(url, opt);
    calls++; sentBody = JSON.parse(opt.body);
    const list = calls > 2 ? [] : [1, 2, 3].map(k => ({
      name: '株式会社サンプル工務店' + (calls * 10 + k),
      location: '東京都港区' + k, prefecture: '東京都',
      phone_number: '03-1234-' + String(1000 + calls * 10 + k),
      company_url: 'https://ex' + k + '.example.jp',
      source_url: 'https://ex' + k + '.example.jp/company'
    }));
    return { ok: true, json: async () => ({
      content: [{ type: 'text', text: JSON.stringify({ companies: list }) }],
      usage: { input_tokens: 6000, output_tokens: 900, server_tool_use: { web_search_requests: 3 } } }) };
  };
  document.getElementById('lb-ai-key').value = 'sk-ant-test-key';
  document.getElementById('lb-industries').value = '工務店';
  document.getElementById('lb-keywords').value = '';
  document.getElementById('lb-prefectures').value = '東京都';
  document.getElementById('lb-count').value = '20';
  document.getElementById('lb-emp-min').value = '10';
  document.getElementById('lb-emp-max').value = '20';
  UI.syncFromInputs();
  await LB.run();                       // ← 左下の主ボタンと同じ経路
  window.fetch = real;
  return { n: LB.companies.length, withTel: LB.companies.filter(c => c.phone_number).length,
           calls, cost: LB._aiCostYen,
           sizeSent: /従業員数 10〜20名/.test(sentBody ? sentBody.messages[0].content : '') };
});
check('名簿なしでWebから探せる', webRun.n === 6, JSON.stringify(webRun));
check('探した会社に電話番号が入っている', webRun.withTel === 6, JSON.stringify(webRun));
check('実費が実測で出る', webRun.cost > 0, JSON.stringify(webRun));
check('規模の希望がAIに伝わっている', webRun.sizeSent, JSON.stringify(webRun));
check('AIを使ったら計器が動く',
  !/AI\s*0\s*回/.test((await page.textContent('#tp-meter')).replace(/\s+/g,' ')),
  await page.textContent('#tp-meter'));
await page.waitForTimeout(500);
check('架電用CSVがそのまま使える', !(await page.isDisabled('#tp-dl-call')), '');
check('結果の見出しに電話番号の数が出る', /6/.test(await page.textContent('#lb-result-title')),
  await page.textContent('#lb-result-title'));

// 料金と作り方
await page.click('text=料金'); await page.waitForTimeout(400);
const info = await page.textContent('#info-body');
check('無料と有料の境目が書いてある', /無料の範囲/.test(info) && /有料の範囲/.test(info) && /python main\.py/.test(info), '');
await page.evaluate(() => UI.close('dlg-info'));

if (errors.length) throw new Error('page errors: '+errors.join(' / '));
ok.forEach(n=>console.log('OK '+n));
console.log('\nALL '+ok.length+' CHECKS PASSED');
await browser.close();
server.close();
