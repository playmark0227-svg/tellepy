/* tellepy 管理画面 - GitHub Pages スタンドアロン版 (localStorage) */

// ===== Storage =====
const Store = {
  get(key, fallback) {
    try { const v = localStorage.getItem('tellepy_' + key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value) {
    localStorage.setItem('tellepy_' + key, JSON.stringify(value));
  }
};

// 初期サンプルデータ投入
(function initSampleData() {
  if (Store.get('initialized', false)) return;

  Store.set('scripts', {
    'example_client.yaml': {
      client_name: '株式会社サンプル',
      product: 'クラウド経費精算ツール「ラクケイ」',
      target: '経理担当者',
      greeting: 'お世話になっております。私、株式会社サンプルのAIアシスタントでございます。本日は経理業務の効率化についてご案内のお電話をさせていただきました。経理ご担当者様はいらっしゃいますでしょうか。',
      pitch: 'ありがとうございます。弊社では、クラウド経費精算ツール「ラクケイ」をご提供しております。領収書をスマートフォンで撮影するだけで自動仕分けが完了し、月次の経費精算業務を最大70%削減した実績がございます。現在、無料トライアルもご用意しておりますが、15分ほどお時間をいただき、デモをご覧いただくことは可能でしょうか。',
      objection_responses: [
        { trigger: '間に合っています', response: 'かしこまりました。ちなみに現在お使いのシステムでは、月にどれくらいのお時間を経費精算に費やされていますか？多くの企業様で、乗り換えにより月20時間以上の削減に成功されています。' },
        { trigger: '忙しい', response: 'お忙しいところ大変失礼いたしました。それでは改めてお時間をいただける日はございますでしょうか。5分程度のオンラインデモもご用意しておりますので、ご都合の良い日時を教えていただけますと幸いです。' },
        { trigger: '資料だけ送って', response: 'かしこまりました。それでは資料をお送りさせていただきます。簡単なデモ動画もございますので、あわせてご確認いただけますと幸いです。資料のお届け先のメールアドレスを教えていただけますでしょうか。' },
        { trigger: '予算がない', response: 'ご事情承知いたしました。実は初期費用ゼロの月額プランもございまして、導入コストを抑えてスタートされる企業様も多くいらっしゃいます。まずは情報としてお持ちいただくだけでも、いかがでしょうか。' },
      ],
      closing: 'ありがとうございます。それでは、デモのお時間を調整させていただければと思います。来週でご都合の良いお日にちはございますでしょうか。',
      farewell: 'お忙しい中お時間をいただき、誠にありがとうございました。それでは失礼いたします。',
    }
  });

  Store.set('history', [
    { id: 1, called_at: '2026-04-12T10:30:00Z', phone_number: '+819012345678', contact_name: '田中太郎', status: 'appointed', appointment_datetime: '2026-04-16 14:00', conversation_log: [
      { role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。私、株式会社サンプルのAIアシスタントでございます。' },
      { role: 'user', content: 'はい、経理の田中です。' },
      { role: 'assistant', content: 'ありがとうございます。弊社ではクラウド経費精算ツール「ラクケイ」をご提供しております。' },
      { role: 'user', content: '少し聞いてみたいですね。' },
      { role: 'assistant', content: 'ありがとうございます。来週でご都合の良い日はございますでしょうか。' },
      { role: 'user', content: '水曜の14時なら空いています。' },
      { role: 'assistant', content: 'かしこまりました。来週水曜14時にデモのお時間を頂戴します。ありがとうございました。' },
    ]},
    { id: 2, called_at: '2026-04-12T11:15:00Z', phone_number: '+819087654321', contact_name: '佐藤花子', status: 'rejected', appointment_datetime: null, conversation_log: [
      { role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' },
      { role: 'user', content: '今ちょっと忙しいので結構です。' },
      { role: 'assistant', content: 'お忙しいところ失礼いたしました。それでは失礼いたします。' },
    ]},
    { id: 3, called_at: '2026-04-12T13:00:00Z', phone_number: '+819011112222', contact_name: null, status: 'absent', appointment_datetime: null, conversation_log: [] },
    { id: 4, called_at: '2026-04-11T09:45:00Z', phone_number: '+819033334444', contact_name: '鈴木一郎', status: 'appointed', appointment_datetime: '2026-04-15 10:00', conversation_log: [
      { role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' },
      { role: 'user', content: 'はい、鈴木です。' },
      { role: 'assistant', content: '月次の経費精算業務を最大70%削減した実績がございます。' },
      { role: 'user', content: '面白そうですね。火曜の午前中でお願いします。' },
      { role: 'assistant', content: 'かしこまりました。火曜10時にお時間を頂戴します。' },
    ]},
    { id: 5, called_at: '2026-04-11T14:20:00Z', phone_number: '+819055556666', contact_name: '高橋美咲', status: 'handoff', appointment_datetime: null, conversation_log: [
      { role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' },
      { role: 'user', content: 'AIじゃなくて人と話したいんですけど。' },
      { role: 'assistant', content: 'かしこまりました。ただいま担当者におつなぎいたします。少々お待ちくださいませ。' },
    ]},
  ]);

  Store.set('settings', {
    twilio_account_sid: '', twilio_auth_token: '', twilio_phone_number: '',
    deepgram_api_key: '', elevenlabs_api_key: '', elevenlabs_voice_id: '',
    anthropic_api_key: '', firebase_credentials_path: '', firebase_project_id: '',
    slack_webhook_url: '', base_url: '', forward_phone_number: '',
  });

  Store.set('initialized', true);
})();

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
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.nav-item').forEach(function(item) {
    item.addEventListener('click', function() { navigate(item.dataset.page); });
  });
  navigate('dashboard');
});

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
  load: function() {
    var history = Store.get('history', []);
    var today = new Date().toISOString().slice(0, 10);
    var todayLogs = history.filter(function(l) { return (l.called_at || '').slice(0, 10) === today; });
    var appointed = todayLogs.filter(function(l) { return l.status === 'appointed'; });

    document.getElementById('stat-total').textContent = todayLogs.length;
    document.getElementById('stat-appointed').textContent = appointed.length;
    document.getElementById('stat-active').textContent = '0';
    document.getElementById('stat-rate').textContent = todayLogs.length > 0 ? Math.round(appointed.length / todayLogs.length * 100) + '%' : '-';

    var settings = Store.get('settings', {});
    var services = {
      'Twilio': !!(settings.twilio_account_sid && settings.twilio_auth_token),
      'Deepgram': !!settings.deepgram_api_key,
      'ElevenLabs': !!settings.elevenlabs_api_key,
      'Anthropic': !!settings.anthropic_api_key,
      'Firebase': !!settings.firebase_credentials_path,
      'Slack': !!settings.slack_webhook_url,
    };
    var grid = document.getElementById('status-grid');
    grid.innerHTML = Object.keys(services).map(function(name) {
      var ok = services[name];
      return '<div class="status-item"><div class="status-dot ' + (ok ? 'ok' : 'ng') + '"></div><div class="name">' + name + '</div></div>';
    }).join('');

    document.getElementById('active-calls-table').innerHTML = '<p style="color:var(--gray-400);font-size:14px;">現在通話中のセッションはありません</p>';
  }
};

// ===== Settings =====
var Settings = {
  load: function() {
    var config = Store.get('settings', {});
    var form = document.getElementById('settings-form');
    Object.keys(config).forEach(function(key) {
      var input = form.querySelector('[name="' + key + '"]');
      if (input) input.value = config[key] || '';
    });
  }
};

document.getElementById('settings-form').addEventListener('submit', function(e) {
  e.preventDefault();
  var data = {};
  e.target.querySelectorAll('input').forEach(function(input) {
    if (input.name) data[input.name] = input.value;
  });
  Store.set('settings', data);
  toast('設定を保存しました');
  // ダッシュボードのステータスも反映
  Dashboard.load();
});

// ===== Scripts =====
var Scripts = {
  load: function() {
    var scripts = Store.get('scripts', {});
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
        '<div class="meta">' +
          '<div>商材: ' + (s.product || '-') + '</div>' +
          '<div>ターゲット: ' + (s.target || '-') + '</div>' +
          '<div>ファイル: ' + filename + '</div>' +
        '</div>' +
        '<div class="btn-group" style="margin-top:10px">' +
          '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();Scripts.edit(\'' + filename + '\')">編集</button>' +
          '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();Scripts.remove(\'' + filename + '\')">削除</button>' +
        '</div></div>';
    }).join('');
  },

  showCreate: function() {
    document.getElementById('script-modal-title').textContent = 'スクリプト作成';
    document.getElementById('script-edit-name').value = '';
    document.getElementById('script-filename').value = '';
    document.getElementById('script-filename').disabled = false;
    document.getElementById('script-client-name').value = '';
    document.getElementById('script-product').value = '';
    document.getElementById('script-target').value = '';
    document.getElementById('script-greeting').value = '';
    document.getElementById('script-pitch').value = '';
    document.getElementById('script-closing').value = '';
    document.getElementById('script-farewell').value = '';
    document.getElementById('objection-list').innerHTML = '';
    this.addObjection();
    document.getElementById('script-modal').classList.remove('hidden');
  },

  edit: function(filename) {
    var scripts = Store.get('scripts', {});
    var s = scripts[filename];
    if (!s) { toast('スクリプトが見つかりません', 'error'); return; }
    document.getElementById('script-modal-title').textContent = 'スクリプト編集';
    document.getElementById('script-edit-name').value = filename;
    document.getElementById('script-filename').value = filename.replace('.yaml', '');
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
  },

  addObjection: function(trigger, response) {
    trigger = trigger || '';
    response = response || '';
    var list = document.getElementById('objection-list');
    var row = document.createElement('div');
    row.className = 'objection-row';
    row.innerHTML = '<input type="text" placeholder="トリガー" value="' + trigger.replace(/"/g, '&quot;') + '">' +
      '<textarea placeholder="返答" rows="1">' + response.replace(/</g, '&lt;') + '</textarea>' +
      '<button type="button" class="btn btn-sm btn-danger" onclick="this.parentElement.remove()" style="flex-shrink:0">&times;</button>';
    list.appendChild(row);
  },

  closeModal: function() {
    document.getElementById('script-modal').classList.add('hidden');
  },

  remove: function(filename) {
    if (!confirm('「' + filename + '」を削除しますか？')) return;
    var scripts = Store.get('scripts', {});
    delete scripts[filename];
    Store.set('scripts', scripts);
    toast('削除しました');
    this.load();
  },

  getFormData: function() {
    var objections = [];
    document.querySelectorAll('#objection-list .objection-row').forEach(function(row) {
      var trigger = row.querySelector('input').value.trim();
      var response = row.querySelector('textarea').value.trim();
      if (trigger && response) objections.push({ trigger: trigger, response: response });
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

document.getElementById('script-form').addEventListener('submit', function(e) {
  e.preventDefault();
  var editName = document.getElementById('script-edit-name').value;
  var filename = document.getElementById('script-filename').value.trim();
  if (!filename) { toast('ファイル名を入力してください', 'error'); return; }
  if (!filename.endsWith('.yaml')) filename += '.yaml';

  var scripts = Store.get('scripts', {});
  if (!editName && scripts[filename]) { toast('同名のスクリプトが既に存在します', 'error'); return; }

  scripts[editName || filename] = Scripts.getFormData();
  Store.set('scripts', scripts);
  toast(editName ? 'スクリプトを更新しました' : 'スクリプトを作成しました');
  Scripts.closeModal();
  Scripts.load();
});

// ===== Calls =====
var Calls = {
  csvFile: null,

  load: function() {
    var scripts = Store.get('scripts', {});
    var sel = document.getElementById('call-script');
    sel.innerHTML = Object.keys(scripts).map(function(f) {
      var s = scripts[f];
      return '<option value="' + f + '">' + (s.client_name || f) + '</option>';
    }).join('');
  },

  initiate: function() {
    var phone = document.getElementById('call-phone').value.trim();
    if (!phone) { toast('電話番号を入力してください', 'error'); return; }
    var script = document.getElementById('call-script').value;

    // デモ用: 履歴に追加
    var history = Store.get('history', []);
    history.unshift({
      id: Date.now(),
      called_at: new Date().toISOString(),
      phone_number: phone,
      contact_name: null,
      status: 'in_progress',
      appointment_datetime: null,
      conversation_log: [{ role: 'assistant', content: 'AIアシスタントがご案内します。お世話になっております。' }],
    });
    Store.set('history', history);
    toast('架電を開始しました（デモ）: ' + phone, 'info');
    document.getElementById('call-phone').value = '';
  },

  handleDrop: function(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    var file = e.dataTransfer.files[0];
    if (file) this.handleFile(file);
  },

  handleFile: function(file) {
    if (!file || !file.name.endsWith('.csv')) {
      toast('CSVファイルを選択してください', 'error');
      return;
    }
    this.csvFile = file;
    var reader = new FileReader();
    var self = this;
    reader.onload = function(e) {
      var lines = e.target.result.split('\n').filter(function(l) { return l.trim(); });
      var preview = document.getElementById('csv-preview');
      preview.innerHTML = '<table><thead><tr>' + lines[0].split(',').map(function(h) { return '<th>' + h.trim() + '</th>'; }).join('') + '</tr></thead><tbody>' +
        lines.slice(1, 11).map(function(line) { return '<tr>' + line.split(',').map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('') + '</tr>'; }).join('') +
        '</tbody></table>' + (lines.length > 11 ? '<p style="font-size:12px;color:var(--gray-400);margin-top:8px">他 ' + (lines.length - 11) + ' 件...</p>' : '');
      preview.classList.remove('hidden');
      document.getElementById('csv-actions').classList.remove('hidden');
    };
    reader.readAsText(file);
  },

  batchCall: function() {
    if (!this.csvFile) return;
    var reader = new FileReader();
    reader.onload = function(e) {
      var lines = e.target.result.split('\n').filter(function(l) { return l.trim(); });
      var count = lines.length - 1;
      var history = Store.get('history', []);
      lines.slice(1).forEach(function(line) {
        var cols = line.split(',');
        history.unshift({
          id: Date.now() + Math.random(),
          called_at: new Date().toISOString(),
          phone_number: (cols[0] || '').trim(),
          contact_name: null,
          status: 'in_progress',
          appointment_datetime: null,
          conversation_log: [],
        });
      });
      Store.set('history', history);
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
  load: function() {
    var status = document.getElementById('history-filter-status').value;
    var history = Store.get('history', []);
    if (status) {
      history = history.filter(function(l) { return l.status === status; });
    }
    var tbody = document.getElementById('history-tbody');
    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--gray-400);">データがありません</td></tr>';
      return;
    }
    tbody.innerHTML = history.map(function(log) {
      var date = log.called_at ? new Date(log.called_at).toLocaleString('ja-JP') : '-';
      var badges = {
        appointed: '<span class="badge badge-ok">アポ獲得</span>',
        rejected: '<span class="badge badge-ng">断り</span>',
        absent: '<span class="badge badge-warn">不在</span>',
        handoff: '<span class="badge badge-info">ハンドオフ</span>',
        in_progress: '<span class="badge badge-info">通話中</span>',
        error: '<span class="badge badge-ng">エラー</span>',
      };
      var statusBadge = badges[log.status] || '<span class="badge">' + log.status + '</span>';
      var logJson = JSON.stringify(log.conversation_log || []).replace(/'/g, "\\'").replace(/"/g, '&quot;');
      return '<tr>' +
        '<td>' + date + '</td>' +
        '<td>' + (log.phone_number || '-') + '</td>' +
        '<td>' + (log.contact_name || '-') + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td>' + (log.appointment_datetime || '-') + '</td>' +
        '<td><button class="btn btn-sm btn-secondary" onclick=\'History.showLog(' + logJson + ')\'>ログ</button></td>' +
      '</tr>';
    }).join('');
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
