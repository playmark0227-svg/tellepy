/* telepy 管理画面 - Firebase Firestore 永続化版 */

// ===== Firebase Config (直接埋め込み) =====
var FIREBASE_CONFIG = {
  apiKey: "AIzaSyAlY6wW9jPEw46RzrV3g04vzJJdMfVcGAk",
  authDomain: "telepy-3ef44.firebaseapp.com",
  projectId: "telepy-3ef44",
  storageBucket: "telepy-3ef44.firebasestorage.app",
  messagingSenderId: "235576373254",
  appId: "1:235576373254:web:1dac35cc7e5e68d02a5387"
};

// ===== Firebase Store =====
var db = null;

function col(name) { return db.collection(name); }

var Store = {
  async get(collection, docId) {
    var doc = await col(collection).doc(docId).get();
    return doc.exists ? doc.data() : null;
  },
  async set(collection, docId, data) {
    await col(collection).doc(docId).set(data, { merge: true });
  },
  async getAll(collection) {
    var snap = await col(collection).get();
    var result = {};
    snap.forEach(function(doc) { result[doc.id] = doc.data(); });
    return result;
  },
  async delete(collection, docId) {
    await col(collection).doc(docId).delete();
  },
  async query(collection, field, op, value, limit) {
    var q = col(collection).where(field, op, value);
    if (limit) q = q.limit(limit);
    var snap = await q.get();
    var arr = [];
    snap.forEach(function(doc) { arr.push({id: doc.id, ...doc.data()}); });
    return arr;
  }
};

// ===== Setup Flow =====
var Setup = {
  connect: async function() {
    var el = document.getElementById('setup-config');
    var errEl = document.getElementById('setup-error');
    errEl.classList.add('hidden');

    var raw = el.value.trim();
    try {
      // handle JS object format (without quotes on keys) by wrapping
      var config;
      if (raw.startsWith('{')) {
        config = JSON.parse(raw);
      } else {
        // try extracting from pasted code block
        var match = raw.match(/\{[\s\S]*\}/);
        if (match) config = JSON.parse(match[0]);
        else throw new Error('設定が見つかりません');
      }

      if (!config.apiKey || !config.projectId) {
        throw new Error('apiKey と projectId は必須です');
      }

      firebase.initializeApp(config);
      db = firebase.firestore();

      // test connection
      await db.collection('_ping').doc('test').set({t: Date.now()});
      await db.collection('_ping').doc('test').delete();

      localStorage.setItem('telepy_fb_config', JSON.stringify(config));
      document.getElementById('setup-overlay').classList.add('hidden');
      toast('Firebase接続完了！');
      await initApp();
    } catch (e) {
      errEl.textContent = '接続エラー: ' + e.message;
      errEl.classList.remove('hidden');
    }
  }
};

// ===== Initialization =====
document.addEventListener('DOMContentLoaded', async function() {
  try {
    if (!firebase.apps.length) firebase.initializeApp(FIREBASE_CONFIG);
    db = firebase.firestore();
    await initApp();
  } catch (e) {
    console.error('Firebase初期化エラー:', e);
    document.getElementById('setup-overlay').classList.remove('hidden');
  }
});

async function initApp() {
  // nav
  document.querySelectorAll('.nav-item').forEach(function(item) {
    item.addEventListener('click', function() { navigate(item.dataset.page); });
  });

  // seed sample data if empty
  var scripts = await Store.getAll('scripts');
  if (Object.keys(scripts).length === 0) {
    await seedSampleData();
  }

  navigate('dashboard');
}

async function seedSampleData() {
  await Store.set('scripts', 'example_client', {
    client_name: '株式会社サンプル',
    product: 'クラウド経費精算ツール「ラクケイ」',
    target: '経理担当者',
    greeting: 'お世話になっております。私、株式会社サンプルのAIアシスタントでございます。本日は経理業務の効率化についてご案内のお電話をさせていただきました。',
    pitch: '弊社ではクラウド経費精算ツール「ラクケイ」をご提供しております。領収書をスマートフォンで撮影するだけで自動仕分けが完了し、月次の経費精算業務を最大70%削減した実績がございます。',
    objection_responses: [
      { trigger: '間に合っています', response: 'かしこまりました。ちなみに現在お使いのシステムでは月にどれくらいの時間を経費精算に費やされていますか？' },
      { trigger: '忙しい', response: 'お忙しいところ失礼いたしました。5分程度のオンラインデモもございますので、ご都合の良い日時を教えていただけますと幸いです。' },
      { trigger: '資料だけ送って', response: 'かしこまりました。資料とデモ動画をお送りします。メールアドレスを教えていただけますでしょうか。' },
    ],
    closing: 'それでは15分ほどのオンラインデモで具体的なイメージをお持ちいただければと思います。来週でしたら火曜と水曜、どちらがご都合よろしいでしょうか。',
    farewell: 'お忙しい中お時間をいただき、誠にありがとうございました。それでは失礼いたします。',
  });

  var sampleHistory = [
    { called_at: '2026-04-12T10:30:00Z', phone_number: '+819012345678', contact_name: '田中太郎', status: 'appointed', appointment_datetime: '2026-04-16 14:00', conversation_log: [
      { role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' },
      { role: 'user', content: 'はい、経理の田中です。' },
      { role: 'assistant', content: '弊社ではクラウド経費精算ツールをご提供しております。' },
      { role: 'user', content: '水曜の14時なら空いています。' },
    ]},
    { called_at: '2026-04-12T11:15:00Z', phone_number: '+819087654321', contact_name: '佐藤花子', status: 'rejected', appointment_datetime: null, conversation_log: [
      { role: 'assistant', content: 'お世話になっております。' },
      { role: 'user', content: '結構です。' },
    ]},
    { called_at: '2026-04-12T13:00:00Z', phone_number: '+819011112222', contact_name: null, status: 'absent', appointment_datetime: null, conversation_log: [] },
  ];

  for (var i = 0; i < sampleHistory.length; i++) {
    await col('call_history').add(sampleHistory[i]);
  }
}

// ===== Toast =====
function toast(message, type) {
  type = type || 'success';
  var container = document.getElementById('toasts');
  var el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(function() { el.style.opacity = '0'; setTimeout(function() { el.remove(); }, 300); }, 3000);
}

// ===== Navigation =====
function navigate(page) {
  document.querySelectorAll('.page').forEach(function(p) { p.classList.add('hidden'); });
  var el = document.getElementById('page-' + page);
  if (el) el.classList.remove('hidden');
  document.querySelectorAll('.nav-item').forEach(function(n) {
    n.classList.toggle('active', n.dataset.page === page);
  });
  var loaders = { dashboard: Dashboard.load, settings: Settings.load, scripts: Scripts.load, calls: Calls.load, history: History.load };
  if (loaders[page]) loaders[page]();
}

// ===== Dashboard =====
var Dashboard = {
  load: async function() {
    try {
      var settings = (await Store.get('settings', 'main')) || {};
      var services = {
        'Twilio': !!(settings.twilio_account_sid && settings.twilio_auth_token),
        'Deepgram': !!settings.deepgram_api_key,
        'ElevenLabs': !!settings.elevenlabs_api_key,
        'Anthropic': !!settings.anthropic_api_key,
        'Firebase': true,
        'Slack': !!settings.slack_webhook_url,
      };
      var grid = document.getElementById('status-grid');
      grid.innerHTML = Object.keys(services).map(function(name) {
        return '<div class="status-item"><div class="status-dot ' + (services[name] ? 'ok' : 'ng') + '"></div><div class="name">' + name + '</div></div>';
      }).join('');

      // stats
      var snap = await col('call_history').get();
      var today = new Date().toISOString().slice(0, 10);
      var todayLogs = []; var allLogs = [];
      snap.forEach(function(doc) {
        var d = doc.data();
        allLogs.push(d);
        if ((d.called_at || '').slice(0, 10) === today) todayLogs.push(d);
      });
      var appointed = todayLogs.filter(function(l) { return l.status === 'appointed'; });
      document.getElementById('stat-total').textContent = todayLogs.length;
      document.getElementById('stat-appointed').textContent = appointed.length;
      document.getElementById('stat-active').textContent = '0';
      document.getElementById('stat-rate').textContent = todayLogs.length > 0 ? Math.round(appointed.length / todayLogs.length * 100) + '%' : '-';

      document.getElementById('active-calls-table').innerHTML = '<p style="color:var(--gray-400);font-size:14px;">現在通話中のセッションはありません</p>';
    } catch (e) { console.error(e); }
  }
};

// ===== Settings =====
var Settings = {
  load: async function() {
    try {
      var config = (await Store.get('settings', 'main')) || {};
      var form = document.getElementById('settings-form');
      form.querySelectorAll('input').forEach(function(input) {
        if (input.name) input.value = config[input.name] || '';
      });
    } catch (e) { toast('設定の読み込みに失敗しました', 'error'); }
  }
};

document.getElementById('settings-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var data = {};
  e.target.querySelectorAll('input').forEach(function(input) {
    if (input.name) data[input.name] = input.value;
  });
  try {
    await Store.set('settings', 'main', data);
    toast('設定を保存しました');
  } catch (e) { toast('保存に失敗しました: ' + e.message, 'error'); }
});

// ===== Scripts =====
var Scripts = {
  load: async function() {
    try {
      var scripts = await Store.getAll('scripts');
      var list = document.getElementById('script-list');
      var keys = Object.keys(scripts);
      if (keys.length === 0) {
        list.innerHTML = '<p style="color:var(--gray-400)">スクリプトがありません。「新規作成」から作成してください。</p>';
        return;
      }
      list.innerHTML = keys.map(function(filename) {
        var s = scripts[filename];
        return '<div class="script-card" onclick="Scripts.edit(\'' + filename + '\')">' +
          '<h4>' + (s.client_name || filename) + '</h4>' +
          '<div class="meta"><div>商材: ' + (s.product || '-') + '</div><div>ターゲット: ' + (s.target || '-') + '</div><div>ID: ' + filename + '</div></div>' +
          '<div class="btn-group" style="margin-top:10px">' +
          '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();Scripts.edit(\'' + filename + '\')">編集</button>' +
          '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();Scripts.remove(\'' + filename + '\')">削除</button></div></div>';
      }).join('');
    } catch (e) { toast('スクリプトの読み込みに失敗しました', 'error'); }
  },

  showCreate: function() {
    document.getElementById('script-modal-title').textContent = 'スクリプト作成';
    document.getElementById('script-edit-name').value = '';
    document.getElementById('script-filename').value = '';
    document.getElementById('script-filename').disabled = false;
    ['script-client-name','script-product','script-target','script-greeting','script-pitch','script-closing','script-farewell']
      .forEach(function(id) { document.getElementById(id).value = ''; });
    document.getElementById('objection-list').innerHTML = '';
    this.addObjection();
    document.getElementById('script-modal').classList.remove('hidden');
  },

  edit: async function(filename) {
    try {
      var s = await Store.get('scripts', filename);
      if (!s) { toast('スクリプトが見つかりません', 'error'); return; }
      document.getElementById('script-modal-title').textContent = 'スクリプト編集';
      document.getElementById('script-edit-name').value = filename;
      document.getElementById('script-filename').value = filename;
      document.getElementById('script-filename').disabled = true;
      document.getElementById('script-client-name').value = s.client_name || '';
      document.getElementById('script-product').value = s.product || '';
      document.getElementById('script-target').value = s.target || '';
      document.getElementById('script-greeting').value = s.greeting || '';
      document.getElementById('script-pitch').value = s.pitch || '';
      document.getElementById('script-closing').value = s.closing || '';
      document.getElementById('script-farewell').value = s.farewell || '';
      var list = document.getElementById('objection-list');
      list.innerHTML = '';
      (s.objection_responses || []).forEach(function(o) { Scripts.addObjection(o.trigger, o.response); });
      if ((s.objection_responses || []).length === 0) this.addObjection();
      document.getElementById('script-modal').classList.remove('hidden');
    } catch (e) { toast('読み込みに失敗しました', 'error'); }
  },

  addObjection: function(trigger, response) {
    trigger = trigger || ''; response = response || '';
    var list = document.getElementById('objection-list');
    var row = document.createElement('div');
    row.className = 'objection-row';
    row.innerHTML = '<input type="text" placeholder="トリガー" value="' + trigger.replace(/"/g, '&quot;') + '">' +
      '<textarea placeholder="返答" rows="1">' + response.replace(/</g, '&lt;') + '</textarea>' +
      '<button type="button" class="btn btn-sm btn-danger" onclick="this.parentElement.remove()" style="flex-shrink:0">&times;</button>';
    list.appendChild(row);
  },

  closeModal: function() { document.getElementById('script-modal').classList.add('hidden'); },

  remove: async function(filename) {
    if (!confirm('「' + filename + '」を削除しますか？')) return;
    try {
      await Store.delete('scripts', filename);
      toast('削除しました');
      this.load();
    } catch (e) { toast('削除に失敗しました', 'error'); }
  },

  getFormData: function() {
    var objections = [];
    document.querySelectorAll('#objection-list .objection-row').forEach(function(row) {
      var t = row.querySelector('input').value.trim();
      var r = row.querySelector('textarea').value.trim();
      if (t && r) objections.push({ trigger: t, response: r });
    });
    return {
      client_name: document.getElementById('script-client-name').value,
      product: document.getElementById('script-product').value,
      target: document.getElementById('script-target').value,
      greeting: document.getElementById('script-greeting').value,
      pitch: document.getElementById('script-pitch').value,
      objection_responses: objections,
      closing: document.getElementById('script-closing').value,
      farewell: document.getElementById('script-farewell').value,
    };
  }
};

document.getElementById('script-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var editName = document.getElementById('script-edit-name').value;
  var filename = document.getElementById('script-filename').value.trim();
  if (!filename) { toast('ファイル名を入力してください', 'error'); return; }
  try {
    if (!editName) {
      var existing = await Store.get('scripts', filename);
      if (existing) { toast('同名のスクリプトが既に存在します', 'error'); return; }
    }
    await Store.set('scripts', editName || filename, Scripts.getFormData());
    toast(editName ? 'スクリプトを更新しました' : 'スクリプトを作成しました');
    Scripts.closeModal();
    Scripts.load();
  } catch (e) { toast('保存に失敗しました: ' + e.message, 'error'); }
});

// ===== Mood / State helpers =====
var MOODS = {
  neutral: {emoji:'😐', label:'普通'}, curious: {emoji:'🤔', label:'興味'},
  thinking: {emoji:'💭', label:'検討中'}, interested: {emoji:'😊', label:'前向き'},
  positive: {emoji:'😄', label:'好感触'}, annoyed: {emoji:'😒', label:'迷惑'},
  negative: {emoji:'😞', label:'消極的'},
};
var STATE_LABELS = {GREETING:'挨拶',QUALIFYING:'ヒアリング',PITCHING:'提案',CLOSING:'クロージング',OBJECTION:'断り返し',HANDOFF:'ハンドオフ',REJECTED:'拒否'};

// ===== Demo Scenarios =====
var DEMO_SCENARIOS = [
  { name:'アポ獲得',result:'appointed', steps:[
    {state:'GREETING',interest:2,mood:'neutral',strategy:'丁寧な導入',role:'assistant',text:'お世話になっております。私、株式会社サンプルのAIアシスタントでございます。本日は経理業務の効率化についてご案内のお電話をさせていただきました。'},
    {state:'GREETING',interest:2,mood:'neutral',role:'user',text:'はい、経理の田中です。何でしょうか。'},
    {state:'QUALIFYING',interest:3,mood:'curious',strategy:'SPIN質問法',role:'assistant',text:'田中様、お忙しいところ恐れ入ります。御社では毎月の経費精算にどれくらいのお時間をかけていらっしゃいますか？',contact_name:'田中'},
    {state:'QUALIFYING',interest:3,mood:'thinking',role:'user',text:'うーん、月末は結構かかりますね。20時間くらいでしょうか。'},
    {state:'PITCHING',interest:4,mood:'interested',strategy:'課題深掘り → 解決策提示',role:'assistant',text:'弊社のクラウド経費精算ツール「ラクケイ」を導入されたA社様では、月20時間が6時間にまで短縮されました。'},
    {state:'PITCHING',interest:4,mood:'interested',role:'user',text:'それは便利そうですね。弥生と連携できますか？'},
    {state:'PITCHING',interest:4,mood:'positive',strategy:'技術的不安の解消',role:'assistant',text:'はい、弥生とはワンクリックで連携可能です。既存フローを変えずに導入いただけます。'},
    {state:'CLOSING',interest:5,mood:'positive',strategy:'クロージング',role:'assistant',text:'15分ほどのオンラインデモで実際の画面をご覧いただけます。来週、火曜と水曜どちらがよろしいですか。'},
    {state:'CLOSING',interest:5,mood:'positive',role:'user',text:'水曜の14時なら空いていますよ。'},
    {state:'HANDOFF',interest:5,mood:'positive',strategy:'予約確定',role:'assistant',text:'ありがとうございます！来週水曜14時にオンラインデモご予約いただきます。',appointment:'2026-04-16 14:00'},
  ]},
  { name:'断り返し成功',result:'appointed', steps:[
    {state:'GREETING',interest:2,mood:'neutral',strategy:'丁寧な導入',role:'assistant',text:'お世話になっております。経費精算の効率化についてご案内させていただいております。'},
    {state:'GREETING',interest:1,mood:'annoyed',role:'user',text:'営業ですか？今ちょっと忙しいので...'},
    {state:'OBJECTION',interest:2,mood:'neutral',strategy:'共感 → 価値提示',objection:true,role:'assistant',text:'お忙しいところ申し訳ございません。30秒だけお時間いただけますか。同業の企業様で月20時間の作業が6時間に削減できた事例がございます。'},
    {state:'QUALIFYING',interest:3,mood:'curious',role:'user',text:'30秒だけなら。具体的にどういうことですか？'},
    {state:'PITCHING',interest:3,mood:'thinking',strategy:'具体事例で信頼構築',role:'assistant',text:'領収書をスマホ撮影するだけでAIが自動仕分け。OCR精度99.2%で手入力ゼロ。30日間無料お試しいただけます。'},
    {state:'PITCHING',interest:4,mood:'interested',role:'user',text:'無料で試せるんですか。資料を送ってもらえますか？',contact_name:'鈴木'},
    {state:'CLOSING',interest:4,mood:'positive',strategy:'資料送付 → デモ提案',role:'assistant',text:'もちろんです。資料とデモ動画をお送りします。来週10分ほどオンラインでご説明させていただけないでしょうか。'},
    {state:'HANDOFF',interest:4,mood:'positive',role:'user',text:'来週の木曜午前中ならいいですよ。',appointment:'2026-04-17 10:00'},
  ]},
  { name:'不在',result:'absent', steps:[
    {state:'GREETING',interest:1,mood:'neutral',strategy:'丁寧な導入',role:'assistant',text:'お世話になっております。経理ご担当者様はいらっしゃいますでしょうか。'},
    {state:'GREETING',interest:1,mood:'neutral',role:'user',text:'担当者は今外出しております。'},
    {state:'REJECTED',interest:1,mood:'neutral',strategy:'再架電予約',role:'assistant',text:'かしこまりました。改めてお電話させていただきます。失礼いたします。'},
  ]},
  { name:'即断り',result:'rejected', steps:[
    {state:'GREETING',interest:2,mood:'neutral',strategy:'丁寧な導入',role:'assistant',text:'お世話になっております。経費精算の効率化についてご案内させていただいております。'},
    {state:'GREETING',interest:1,mood:'annoyed',role:'user',text:'結構です。今後一切お電話いただかないようお願いします。'},
    {state:'OBJECTION',interest:1,mood:'negative',strategy:'丁寧な終話',objection:true,role:'assistant',text:'大変失礼いたしました。今後のご連絡は控えさせていただきます。'},
    {state:'REJECTED',interest:0,mood:'negative',role:'assistant',text:'お忙しいところ失礼いたしました。'},
  ]},
];

// ===== Parallel Call Engine =====
var CallEngine = {
  sessions: {},   // id -> session data
  nextId: 0,
  viewingId: null, // 右パネルに表示中のID
  tickInterval: null,

  createSession: function(phone) {
    var id = ++this.nextId;
    var scenarioIndex = Math.floor(Math.random() * DEMO_SCENARIOS.length);
    var scenario = DEMO_SCENARIOS[scenarioIndex];
    this.sessions[id] = {
      id: id, phone: phone, scenarioIndex: scenarioIndex,
      state: 'GREETING', interest: 0, mood: 'neutral',
      strategy: '', contact_name: '', appointment: '',
      turnCount: 0, objectionCount: 0,
      chatLog: [], stepIndex: 0, stepTimer: 0,
      startTime: Date.now(), finished: false, result: null,
    };
    // 自動的に最初のセッションをフォーカス
    if (!this.viewingId) this.viewingId = id;
    if (!this.tickInterval) {
      var self = this;
      this.tickInterval = setInterval(function(){ self.tick(); }, 500);
    }
    return id;
  },

  tick: function() {
    var now = Date.now();
    var anyActive = false;
    var self = this;
    Object.keys(this.sessions).forEach(function(id) {
      var s = self.sessions[id];
      if (s.finished) return;
      anyActive = true;
      var scenario = DEMO_SCENARIOS[s.scenarioIndex];
      if (s.stepIndex >= scenario.steps.length) {
        s.finished = true;
        s.result = scenario.result;
        Calls.renderSessions();
        if (parseInt(id) === self.viewingId) self.syncMonitor(s);
        return;
      }
      // 各ステップのタイミング制御
      var step = scenario.steps[s.stepIndex];
      // delayTargetは一度だけ計算してセッションに保持
      if (!s.delayTarget) {
        var base = s.stepIndex === 0 ? 800 : (step.role === 'assistant' ? 2500 : 1800);
        s.delayTarget = base + Math.floor(Math.random() * 800);
      }
      s.stepTimer += 500;
      if (s.stepTimer >= s.delayTarget) {
        self.applyStep(s, step);
        s.stepIndex++;
        s.stepTimer = 0;
        s.delayTarget = null; // 次のステップで再計算
        if (parseInt(id) === self.viewingId) self.syncMonitor(s);
      }
    });
    // タイマー表示更新（常に）
    if (this.viewingId && this.sessions[this.viewingId]) {
      var vs = this.sessions[this.viewingId];
      var elapsed = Math.floor((now - vs.startTime) / 1000);
      document.getElementById('monitor-timer').textContent =
        String(Math.floor(elapsed/60)).padStart(2,'0') + ':' + String(elapsed%60).padStart(2,'0');
    }
    // セッションカードのタイマーも毎秒更新
    Calls.renderSessions();
  },

  applyStep: function(s, step) {
    if (step.state) s.state = step.state;
    if (step.interest !== undefined) s.interest = step.interest;
    if (step.mood) s.mood = step.mood;
    if (step.strategy) s.strategy = step.strategy;
    if (step.contact_name) s.contact_name = step.contact_name;
    if (step.appointment) s.appointment = step.appointment;
    if (step.objection) s.objectionCount++;
    if (step.role === 'user') s.turnCount++;
    s.chatLog.push({role: step.role, text: step.text});
  },

  // 右パネルをセッションの状態に同期
  syncMonitor: function(s) {
    if (!s) {
      // リセット
      document.getElementById('monitor-pulse').className = 'monitor-pulse';
      document.getElementById('monitor-status-label').textContent = '待機中';
      document.getElementById('monitor-timer').textContent = '00:00';
      document.getElementById('monitor-phone').textContent = '-';
      document.getElementById('monitor-header').className = 'monitor-header';
      document.querySelectorAll('.state-node').forEach(function(n){ n.classList.remove('active','passed'); });
      document.getElementById('interest-fill').style.width = '0%';
      document.getElementById('interest-value').textContent = '-';
      document.getElementById('metric-mood').textContent = '-';
      document.getElementById('metric-turns').textContent = '0';
      document.getElementById('metric-objections').textContent = '0 / 3';
      document.getElementById('monitor-strategy').innerHTML = '<div class="strategy-badge">待機中</div>';
      document.getElementById('info-name').textContent = '-';
      document.getElementById('info-appo').textContent = '-';
      document.getElementById('info-notes').textContent = '-';
      document.getElementById('monitor-chat').innerHTML = '<div class="chat-empty">架電を開始すると会話がここに表示されます</div>';
      return;
    }

    // Header
    document.getElementById('monitor-header').className = 'monitor-header' + (s.finished ? '' : ' active');
    document.getElementById('monitor-pulse').className = 'monitor-pulse' + (s.finished ? '' : ' live');
    document.getElementById('monitor-status-label').textContent = s.finished ? '通話終了' : '通話中';
    document.getElementById('monitor-phone').textContent = s.phone;

    // State
    var mainStates = ['GREETING','QUALIFYING','PITCHING','CLOSING'];
    var mainIdx = mainStates.indexOf(s.state);
    document.querySelectorAll('.state-node').forEach(function(n){ n.classList.remove('active','passed'); });
    if (mainIdx >= 0) {
      for (var i = 0; i < mainIdx; i++) {
        var nd = document.querySelector('.state-node[data-state="'+mainStates[i]+'"]');
        if (nd) nd.classList.add('passed');
      }
    }
    var an = document.querySelector('.state-node[data-state="'+s.state+'"]');
    if (an) an.classList.add('active');

    // Metrics
    var pct = s.interest > 0 ? (s.interest / 5) * 100 : 0;
    document.getElementById('interest-fill').style.width = pct + '%';
    document.getElementById('interest-value').textContent = s.interest || '-';
    var m = MOODS[s.mood];
    document.getElementById('metric-mood').textContent = m ? m.emoji + ' ' + m.label : '-';
    document.getElementById('metric-turns').textContent = s.turnCount;
    document.getElementById('metric-objections').textContent = s.objectionCount + ' / 3';

    // Strategy
    document.getElementById('monitor-strategy').innerHTML = s.strategy
      ? '<div class="strategy-badge active">' + s.strategy + '</div>'
      : '<div class="strategy-badge">待機中</div>';

    // Info
    document.getElementById('info-name').textContent = s.contact_name ? s.contact_name + '様' : '-';
    document.getElementById('info-appo').textContent = s.appointment || '-';
    document.getElementById('info-notes').textContent = '-';

    // Chat
    var chat = document.getElementById('monitor-chat');
    chat.innerHTML = s.chatLog.map(function(msg) {
      var isAI = msg.role === 'assistant';
      return '<div class="chat-msg ' + (isAI?'ai':'user') + '">' +
        '<div class="chat-avatar '+(isAI?'ai':'user')+'">'+(isAI?'🤖':'👤')+'</div>' +
        '<div class="chat-bubble"><div class="chat-role '+(isAI?'ai':'')+'">'+(isAI?'AI':'相手')+'</div>' +
        '<div class="chat-text">'+msg.text+'</div></div></div>';
    }).join('');
    chat.scrollTop = chat.scrollHeight;
  },

  focusSession: function(id) {
    this.viewingId = id;
    var s = this.sessions[id];
    this.syncMonitor(s || null);
    Calls.renderSessions();
  },
};

// ===== Calls =====
var Calls = {
  csvFile: null,

  load: async function() {
    try {
      var scripts = await Store.getAll('scripts');
      var sel = document.getElementById('call-script');
      sel.innerHTML = Object.keys(scripts).map(function(f) {
        return '<option value="' + f + '">' + (scripts[f].client_name || f) + '</option>';
      }).join('');
    } catch (e) { /* ignore */ }
    this.renderSessions();
  },

  initiate: async function() {
    var phone = document.getElementById('call-phone').value.trim();
    if (!phone) { toast('電話番号を入力してください', 'error'); return; }

    var id = CallEngine.createSession(phone);
    CallEngine.focusSession(id);
    this.renderSessions();

    // Firestore に記録
    try {
      await col('call_history').add({
        called_at: new Date().toISOString(),
        phone_number: phone, contact_name: null,
        status: 'in_progress', appointment_datetime: null,
        conversation_log: [{role:'assistant',content:'AIアシスタントがご案内します。'}],
      });
    } catch (e) { /* ignore */ }

    toast('架電を開始しました: ' + phone, 'info');
    document.getElementById('call-phone').value = '';
  },

  renderSessions: function() {
    var el = document.getElementById('call-sessions');
    var ids = Object.keys(CallEngine.sessions);
    document.getElementById('session-count').textContent = ids.length + '件';

    if (ids.length === 0) {
      el.innerHTML = '<p class="sessions-empty" style="color:var(--gray-400);font-size:14px;">通話中のセッションはありません</p>';
      return;
    }

    el.innerHTML = ids.map(function(id) {
      var s = CallEngine.sessions[id];
      var elapsed = Math.floor((Date.now() - s.startTime) / 1000);
      var min = String(Math.floor(elapsed/60)).padStart(2,'0');
      var sec = String(elapsed%60).padStart(2,'0');
      var moodInfo = MOODS[s.mood] || {emoji:'😐',label:'普通'};
      var stateLabel = STATE_LABELS[s.state] || s.state;
      var selected = parseInt(id) === CallEngine.viewingId;
      var interestPct = s.interest > 0 ? (s.interest / 5) * 100 : 0;

      // ステータスの色
      var stateClass = 'badge-info';
      if (s.state === 'HANDOFF') stateClass = 'badge-ok';
      else if (s.state === 'REJECTED') stateClass = 'badge-ng';
      else if (s.state === 'OBJECTION') stateClass = 'badge-warn';

      // 結果バッジ
      var resultBadge = '';
      if (s.finished) {
        var rMap = {appointed:'badge-ok',rejected:'badge-ng',absent:'badge-warn'};
        var rLabel = {appointed:'アポ獲得',rejected:'断り',absent:'不在'};
        resultBadge = '<span class="badge '+(rMap[s.result]||'badge-info')+'">'+(rLabel[s.result]||s.result)+'</span>';
      }

      return '<div class="session-card' + (selected ? ' selected' : '') + (s.finished ? ' finished' : '') + '" onclick="CallEngine.focusSession('+id+')">' +
        '<div class="session-card-top">' +
          '<div class="session-card-phone">' +
            '<span class="session-pulse '+(s.finished?'off':'on')+'"></span>' +
            s.phone +
          '</div>' +
          '<div class="session-card-timer">' + min + ':' + sec + '</div>' +
        '</div>' +
        '<div class="session-card-mid">' +
          '<span class="badge '+stateClass+'" style="font-size:11px">' + stateLabel + '</span>' +
          resultBadge +
          '<span style="font-size:14px">' + moodInfo.emoji + '</span>' +
          (s.contact_name ? '<span class="session-contact">'+s.contact_name+'様</span>' : '') +
        '</div>' +
        '<div class="session-card-bar">' +
          '<div class="session-interest-label">関心度</div>' +
          '<div class="session-interest-track"><div class="session-interest-fill" style="width:'+interestPct+'%"></div></div>' +
          '<div class="session-interest-val">' + (s.interest || '-') + '</div>' +
        '</div>' +
        (s.strategy ? '<div class="session-card-strategy">'+s.strategy+'</div>' : '') +
      '</div>';
    }).join('');
  },

  handleDrop: function(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    var file = e.dataTransfer.files[0];
    if (file) this.handleFile(file);
  },

  handleFile: function(file) {
    if (!file || !file.name.endsWith('.csv')) { toast('CSVファイルを選択してください', 'error'); return; }
    this.csvFile = file;
    var reader = new FileReader();
    reader.onload = function(e) {
      var lines = e.target.result.split('\n').filter(function(l) { return l.trim(); });
      var preview = document.getElementById('csv-preview');
      preview.innerHTML = '<table><thead><tr>' + lines[0].split(',').map(function(h) { return '<th>' + h.trim() + '</th>'; }).join('') + '</tr></thead><tbody>' +
        lines.slice(1, 11).map(function(line) { return '<tr>' + line.split(',').map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('') + '</tr>'; }).join('') +
        '</tbody></table>';
      preview.classList.remove('hidden');
      document.getElementById('csv-actions').classList.remove('hidden');
    };
    reader.readAsText(file);
  },

  batchCall: async function() {
    if (!this.csvFile) return;
    var reader = new FileReader();
    reader.onload = async function(e) {
      var lines = e.target.result.split('\n').filter(function(l) { return l.trim(); });
      var count = 0;
      for (var i = 1; i < lines.length; i++) {
        var cols = lines[i].split(',');
        var phone = (cols[0] || '').trim();
        if (!phone) continue;
        CallEngine.createSession(phone);
        count++;
      }
      Calls.renderSessions();
      toast('一括架電開始: ' + count + '件', 'info');
      Calls.clearCsv();
    };
    reader.readAsText(this.csvFile);
  },

  clearCsv: function() {
    this.csvFile = null;
    document.getElementById('csv-preview').classList.add('hidden');
    document.getElementById('csv-actions').classList.add('hidden');
    document.getElementById('csv-file').value = '';
  }
};

// ===== History =====
var History = {
  load: async function() {
    try {
      var status = document.getElementById('history-filter-status').value;
      var q = col('call_history').orderBy('called_at', 'desc').limit(50);
      if (status) q = q.where('status', '==', status);

      var snap = await q.get();
      var logs = [];
      snap.forEach(function(doc) { logs.push({id: doc.id, ...doc.data()}); });

      var tbody = document.getElementById('history-tbody');
      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--gray-400);">データがありません</td></tr>';
        return;
      }
      tbody.innerHTML = logs.map(function(log) {
        var date = log.called_at ? new Date(log.called_at).toLocaleString('ja-JP') : '-';
        var badges = {
          appointed: '<span class="badge badge-ok">アポ獲得</span>',
          rejected: '<span class="badge badge-ng">断り</span>',
          absent: '<span class="badge badge-warn">不在</span>',
          handoff: '<span class="badge badge-info">ハンドオフ</span>',
          in_progress: '<span class="badge badge-info">通話中</span>',
        };
        var statusBadge = badges[log.status] || '<span class="badge">' + (log.status||'') + '</span>';
        return '<tr>' +
          '<td>' + date + '</td>' +
          '<td>' + (log.phone_number || '-') + '</td>' +
          '<td>' + (log.contact_name || '-') + '</td>' +
          '<td>' + statusBadge + '</td>' +
          '<td>' + (log.appointment_datetime || '-') + '</td>' +
          '<td><button class="btn btn-sm btn-secondary" onclick="History.showLogById(\'' + log.id + '\')">ログ</button></td>' +
        '</tr>';
      }).join('');
    } catch (e) {
      console.error(e);
      toast('履歴の読み込みに失敗しました', 'error');
    }
  },

  showLogById: async function(docId) {
    var doc = await col('call_history').doc(docId).get();
    var log = doc.exists ? (doc.data().conversation_log || []) : [];
    this.showLog(log);
  },

  showLog: function(log) {
    var body = document.getElementById('log-modal-body');
    if (!log || log.length === 0) {
      body.innerHTML = '<p style="color:var(--gray-400)">会話ログがありません</p>';
    } else {
      body.innerHTML = log.map(function(msg) {
        var isAI = msg.role === 'assistant';
        return '<div style="margin-bottom:12px;padding:10px;border-radius:8px;background:' + (isAI ? '#eef2ff' : '#f3f4f6') + '">' +
          '<div style="font-size:11px;font-weight:600;color:' + (isAI ? 'var(--primary)' : 'var(--gray-500)') + ';margin-bottom:4px">' + (isAI ? 'AI' : '相手') + '</div>' +
          '<div style="font-size:14px">' + msg.content + '</div></div>';
      }).join('');
    }
    document.getElementById('log-modal').classList.remove('hidden');
  }
};
