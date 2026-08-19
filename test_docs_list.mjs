/* ブラウザ版（docs/list.html）のロジックを実ブラウザで直接呼んで検証する。
 *
 *   node test_docs_list.mjs
 *
 * 画面操作ではなく中の関数そのものを叩くので、文字コード判定・CSVの崩れ・
 * 絞り込み・並べ替えの偏りといった、目で見て気づけない部分まで確かめられる。
 * Playwright（Chromium）が必要。CIに無い場合はこのテストだけスキップして構わない。
 */
import { createServer } from 'http';
import { readFile } from 'fs/promises';
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

const browser = await chromium.launch(EXE ? { executablePath: EXE } : {});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => errors.push(String(e)));
await page.goto(BASE + '/list.html');


const ok = [];
function check(name, cond, detail) {
  if (!cond) throw new Error(`${name} が失敗: ${detail}`);
  ok.push(name);
}

// --- ① 業種だけ入れて社名キーワードを空にしても、ちゃんと絞られる
const industryOnly = await page.evaluate(() => {
  document.getElementById('lb-industries').value = '飲食店';
  document.getElementById('lb-keywords').value = '';
  const c = LB.collectCriteria();
  const rows = [];
  for (let i = 0; i < 20; i++) {
    rows.push({ name: '佐藤建設株式会社' + i, prefecture: '東京都', location: '東京都港区',
                capital_stock: null, employee_number: null, company_url: '', phone_number: '',
                corporate_number: '', postal_code: '', industry: '', founding_year: null,
                representative_name: '', match_reason: '' });
  }
  rows.push({ name: '山田飲食店', prefecture: '東京都', location: '東京都港区',
              capital_stock: null, employee_number: null, company_url: '', phone_number: '',
              corporate_number: '', postal_code: '', industry: '', founding_year: null,
              representative_name: '', match_reason: '' });
  const opts = { includeUnknownEmployee: true, strictCapital: false };
  return { keywords: c.name_keywords,
           matched: rows.filter(r => matchesCriteria(r, c, opts)).map(r => r.name) };
});
check('業種だけでも絞り込みが効く', industryOnly.matched.length === 1
  && industryOnly.matched[0] === '山田飲食店',
  JSON.stringify(industryOnly));

// プリセットのある業種は関連語まで広がる
const preset = await page.evaluate(() => {
  document.getElementById('lb-industries').value = '工務店';
  document.getElementById('lb-keywords').value = '';
  return LB.collectCriteria().name_keywords;
});
check('プリセット業種は関連キーワードに展開', preset.includes('建設') && preset.includes('工務店'),
  JSON.stringify(preset));

// --- ② 都道府県の読み取り（東京都で京都府を巻き込まない／一都三県を展開）
const prefs = await page.evaluate(() => ({
  tokyo: parseHeuristic('工務店のリスト。東京都と神奈川県で1000件').prefectures,
  kyoto: parseHeuristic('工務店を京都で100件').prefectures,
  region: parseHeuristic('工務店・不動産、従業員10-20名、一都三県で1000件').prefectures,
}));
check('「東京都」で京都府を巻き込まない',
  JSON.stringify(prefs.tokyo) === JSON.stringify(['東京都', '神奈川県']), JSON.stringify(prefs.tokyo));
check('「京都」は京都府として読む',
  JSON.stringify(prefs.kyoto) === JSON.stringify(['京都府']), JSON.stringify(prefs.kyoto));
check('「一都三県」を4県に展開',
  JSON.stringify(prefs.region) === JSON.stringify(['東京都', '神奈川県', '千葉県', '埼玉県']),
  JSON.stringify(prefs.region));

// --- ③ 社名に " が1つ混じっても、以降の行を飲み込まない
const quote = await page.evaluate(() => {
  const s = makeSearcher({ name_keywords: ['工務店'], prefectures: [], industries: [],
                           employee_min: null, employee_max: null, capital_min: null,
                           capital_max: null, target_count: 100 },
                         { includeUnknownEmployee: true, strictCapital: false, cap: 100,
                           onProgress: function() {} });
  s.feed('法人名,所在地,電話番号\nA"B工務店,東京都港区,03-1\n普通の工務店,東京都港区,03-2\nもう一つの工務店,東京都港区,03-3\n');
  s.flush();
  return { scanned: s.getScanned(), names: s.getResults().map(c => c.name) };
});
check('壊れた引用符でも残りの行を失わない', quote.scanned === 3 && quote.names.length === 3,
  JSON.stringify(quote));

// --- ④ 列名が英語のShift_JISファイルを取りこぼさない
const enc = await page.evaluate(async () => {
  // CP932（Shift_JIS）のバイト列を手で組む
  const sjis = { '株': [0x8a, 0x94], '式': [0x8e, 0xae], '会': [0x89, 0xef], '社': [0x8e, 0xd0],
                 '東': [0x93, 0x8c], '京': [0x8b, 0x9e], '都': [0x93, 0x73],
                 '港': [0x8d, 0x60], '区': [0x8b, 0xe6], '工': [0x8d, 0x48],
                 '務': [0x96, 0xb1], '店': [0x93, 0x58] };
  const bytes = [];
  const push = (s) => {
    for (const ch of s) {
      if (sjis[ch]) bytes.push(...sjis[ch]);
      else bytes.push(ch.charCodeAt(0));
    }
  };
  push('name,address,phone_number,capital\n');
  for (let i = 0; i < 40; i++) push('株式会社工務店,東京都港区,03-1234-5678,8000000\n');
  const file = new File([new Uint8Array(bytes)], 'sjis.csv', { type: 'text/csv' });
  const detected = await resolveEncoding(file, 'auto');
  const out = await searchFile(file, { name_keywords: ['工務店'], prefectures: ['東京都'],
                                       industries: [], employee_min: null, employee_max: null,
                                       capital_min: null, capital_max: null, target_count: 100 },
                               { encoding: 'auto', includeUnknownEmployee: true,
                                 strictCapital: false, cap: 100, onProgress: function() {} });
  return { detected, count: out.companies.length, first: (out.companies[0] || {}).name };
});
check('英語の列名でもShift_JISを見抜く', enc.detected === 'shift_jis', JSON.stringify(enc));
check('Shift_JISのファイルから会社を拾える', enc.count === 40 && enc.first === '株式会社工務店',
  JSON.stringify(enc));

// --- ⑤ 上限で打ち切ったことを隠さない／選ばれる1000件が五十音の先頭に偏らない
const trunc = await page.evaluate(async () => {
  const rows = ['法人番号,法人名,所在地'];
  const names = 'あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ';
  for (let i = 0; i < 6000; i++) {
    rows.push(`${1000000000000 + i},${names[i % names.length]}${i}工務店,東京都港区${i}`);
  }
  const file = new File([rows.join('\n') + '\n'], 'big.csv', { type: 'text/csv' });
  const criteria = { name_keywords: ['工務店'], prefectures: ['東京都'], industries: [],
                     employee_min: null, employee_max: null, capital_min: null,
                     capital_max: null, target_count: 100 };
  const out = await searchFiles([file], criteria,
    { encoding: 'utf-8', includeUnknownEmployee: true, strictCapital: false,
      cap: 2000, onProgress: function() {} });
  // 選ばれた100社が、ファイル全体（6000行）のどのあたりから来ているか
  const idx = out.companies.map(c => parseInt(c.corporate_number, 10) - 1000000000000);
  const buckets = [0, 0, 0, 0, 0];
  idx.forEach(i => { buckets[Math.min(4, Math.floor(i / 400))]++; });
  return { truncated: out.truncated, total: out.total, buckets: buckets,
           minIdx: Math.min(...idx), maxIdx: Math.max(...idx),
           firstNames: out.companies.slice(0, 5).map(c => c.name) };
});
check('上限で打ち切ったことを結果に残す', trunc.truncated === true && trunc.total === 2000,
  JSON.stringify(trunc));
check('選ばれる社が五十音の先頭に偏らない',
  trunc.maxIdx - trunc.minIdx > 1500 && trunc.buckets.every(n => n >= 10),
  JSON.stringify(trunc));

if (errors.length) throw new Error('page errors: ' + errors.join(' / '));
ok.forEach(n => console.log('OK ' + n));
console.log(`\nALL ${ok.length} LOGIC CHECKS PASSED`);
await browser.close();
server.close();
