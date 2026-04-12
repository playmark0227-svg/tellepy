/* telepy 管理画面 - Firebase Firestore 永続化版 */

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
  var saved = localStorage.getItem('telepy_fb_config');
  if (saved) {
    try {
      var config = JSON.parse(saved);
      if (!firebase.apps.length) firebase.initializeApp(config);
      db = firebase.firestore();
      await initApp();
    } catch (e) {
      console.error(e);
      localStorage.removeItem('telepy_fb_config');
      document.getElementById('setup-overlay').classList.remove('hidden');
    }
  } else {
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
  },

  initiate: async function() {
    var phone = document.getElementById('call-phone').value.trim();
    if (!phone) { toast('電話番号を入力してください', 'error'); return; }
    try {
      await col('call_history').add({
        called_at: new Date().toISOString(),
        phone_number: phone,
        contact_name: null,
        status: 'in_progress',
        appointment_datetime: null,
        conversation_log: [{ role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' }],
      });
      toast('架電を開始しました（デモ）: ' + phone, 'info');
      document.getElementById('call-phone').value = '';
    } catch (e) { toast('エラー: ' + e.message, 'error'); }
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
        await col('call_history').add({
          called_at: new Date().toISOString(),
          phone_number: phone,
          contact_name: null,
          status: 'in_progress',
          appointment_datetime: null,
          conversation_log: [],
        });
        count++;
      }
      toast('一括架電開始（デモ）: ' + count + '件', 'info');
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
