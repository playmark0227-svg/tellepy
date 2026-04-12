/* tellepy 管理画面 - メインアプリケーション */

// ===== API Helper =====
async function api(method, url, data = null) {
  const opts = { method, headers: {} };
  if (data !== null && !(data instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(data);
  } else if (data instanceof FormData) {
    opts.body = data;
  }
  const res = await fetch('/api' + url, opts);
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new Error(json?.detail || res.statusText);
  return json;
}

// ===== Toast =====
function toast(message, type = 'success') {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}

// ===== Navigation =====
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.page));
  });
  navigate('dashboard');
});

function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  document.getElementById('page-' + page)?.classList.remove('hidden');
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.page === page);
  });
  // Load page data
  const loaders = { dashboard: Dashboard.load, settings: Settings.load, scripts: Scripts.load, calls: Calls.load, history: History.load };
  loaders[page]?.();
}

// ===== Dashboard =====
const Dashboard = {
  async load() {
    try {
      const [sessions, status] = await Promise.all([
        api('GET', '/sessions'),
        api('GET', '/status'),
      ]);
      // Stats
      document.getElementById('stat-active').textContent = Object.keys(sessions).length;
      document.getElementById('stat-total').textContent = status.today_calls ?? '-';
      document.getElementById('stat-appointed').textContent = status.today_appointed ?? '-';
      const total = status.today_calls || 0;
      const appointed = status.today_appointed || 0;
      document.getElementById('stat-rate').textContent = total > 0 ? Math.round(appointed / total * 100) + '%' : '-';

      // Connection status
      const grid = document.getElementById('status-grid');
      const services = status.services || {};
      grid.innerHTML = Object.entries(services).map(([name, ok]) =>
        `<div class="status-item">
          <div class="status-dot ${ok ? 'ok' : 'ng'}"></div>
          <div class="name">${name}</div>
        </div>`
      ).join('');

      // Active calls
      this.renderActiveCalls(sessions);
    } catch (e) {
      console.error(e);
    }
  },

  renderActiveCalls(sessions) {
    const el = document.getElementById('active-calls-table');
    const entries = Object.entries(sessions);
    if (entries.length === 0) {
      el.innerHTML = '<p style="color:var(--gray-400);font-size:14px;">現在通話中のセッションはありません</p>';
      return;
    }
    el.innerHTML = `<table><thead><tr><th>SID</th><th>電話番号</th><th>状態</th><th>メッセージ数</th></tr></thead><tbody>` +
      entries.map(([sid, s]) =>
        `<tr><td style="font-family:monospace;font-size:12px">${sid.slice(0,12)}...</td><td>${s.phone_number}</td><td><span class="badge badge-info">${s.state}</span></td><td>${s.message_count}</td></tr>`
      ).join('') + '</tbody></table>';
  }
};

// ===== Settings =====
const Settings = {
  async load() {
    try {
      const config = await api('GET', '/settings');
      const form = document.getElementById('settings-form');
      Object.entries(config).forEach(([key, val]) => {
        const input = form.querySelector(`[name="${key}"]`);
        if (input) input.value = val || '';
      });
    } catch (e) {
      toast('設定の読み込みに失敗しました', 'error');
    }
  },
};

document.getElementById('settings-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = {};
  form.querySelectorAll('input').forEach(input => {
    if (input.name) data[input.name] = input.value;
  });
  try {
    await api('PUT', '/settings', data);
    toast('設定を保存しました');
  } catch (e) {
    toast('保存に失敗しました: ' + e.message, 'error');
  }
});

// ===== Scripts =====
const Scripts = {
  async load() {
    try {
      const scripts = await api('GET', '/scripts');
      const list = document.getElementById('script-list');
      if (scripts.length === 0) {
        list.innerHTML = '<p style="color:var(--gray-400)">スクリプトがありません。「新規作成」から作成してください。</p>';
        return;
      }
      list.innerHTML = scripts.map(s =>
        `<div class="script-card" onclick="Scripts.edit('${s.filename}')">
          <h4>${s.client_name || s.filename}</h4>
          <div class="meta">
            <div>商材: ${s.product || '-'}</div>
            <div>ターゲット: ${s.target || '-'}</div>
            <div>ファイル: ${s.filename}</div>
          </div>
          <div class="btn-group" style="margin-top:10px">
            <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();Scripts.edit('${s.filename}')">編集</button>
            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();Scripts.remove('${s.filename}')">削除</button>
          </div>
        </div>`
      ).join('');
    } catch (e) {
      toast('スクリプトの読み込みに失敗しました', 'error');
    }
  },

  showCreate() {
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

  async edit(filename) {
    try {
      const s = await api('GET', '/scripts/' + filename);
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
      // Objections
      const list = document.getElementById('objection-list');
      list.innerHTML = '';
      (s.objection_responses || []).forEach(o => this.addObjection(o.trigger, o.response));
      if ((s.objection_responses || []).length === 0) this.addObjection();
      document.getElementById('script-modal').classList.remove('hidden');
    } catch (e) {
      toast('スクリプトの読み込みに失敗しました', 'error');
    }
  },

  addObjection(trigger = '', response = '') {
    const list = document.getElementById('objection-list');
    const row = document.createElement('div');
    row.className = 'objection-row';
    row.innerHTML = `
      <input type="text" placeholder="トリガー" value="${trigger}">
      <textarea placeholder="返答" rows="1">${response}</textarea>
      <button type="button" class="btn btn-sm btn-danger" onclick="this.parentElement.remove()" style="flex-shrink:0">&times;</button>`;
    list.appendChild(row);
  },

  closeModal() {
    document.getElementById('script-modal').classList.add('hidden');
  },

  async remove(filename) {
    if (!confirm(`「${filename}」を削除しますか？`)) return;
    try {
      await api('DELETE', '/scripts/' + filename);
      toast('削除しました');
      this.load();
    } catch (e) {
      toast('削除に失敗しました: ' + e.message, 'error');
    }
  },

  getFormData() {
    const objections = [];
    document.querySelectorAll('#objection-list .objection-row').forEach(row => {
      const trigger = row.querySelector('input').value.trim();
      const response = row.querySelector('textarea').value.trim();
      if (trigger && response) objections.push({ trigger, response });
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

document.getElementById('script-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const editName = document.getElementById('script-edit-name').value;
  const filename = document.getElementById('script-filename').value.trim();
  if (!filename) { toast('ファイル名を入力してください', 'error'); return; }
  const data = Scripts.getFormData();
  try {
    if (editName) {
      await api('PUT', '/scripts/' + editName, data);
      toast('スクリプトを更新しました');
    } else {
      await api('POST', '/scripts/' + filename, data);
      toast('スクリプトを作成しました');
    }
    Scripts.closeModal();
    Scripts.load();
  } catch (e) {
    toast('保存に失敗しました: ' + e.message, 'error');
  }
});

// ===== Calls =====
const Calls = {
  csvFile: null,

  async load() {
    // Load scripts into selector
    try {
      const scripts = await api('GET', '/scripts');
      const sel = document.getElementById('call-script');
      sel.innerHTML = scripts.map(s =>
        `<option value="${s.filename}">${s.client_name || s.filename}</option>`
      ).join('');
    } catch (e) { /* ignore */ }
    this.refreshSessions();
  },

  async initiate() {
    const phone = document.getElementById('call-phone').value.trim();
    const script = document.getElementById('call-script').value;
    if (!phone) { toast('電話番号を入力してください', 'error'); return; }
    try {
      const res = await api('POST', '/call/initiate', { phone_number: phone, script_path: script || null });
      toast(`架電開始: ${res.call_sid}`);
      document.getElementById('call-phone').value = '';
      this.refreshSessions();
    } catch (e) {
      toast('架電に失敗しました: ' + e.message, 'error');
    }
  },

  handleDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) this.handleFile(file);
  },

  handleFile(file) {
    if (!file || !file.name.endsWith('.csv')) {
      toast('CSVファイルを選択してください', 'error');
      return;
    }
    this.csvFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      const lines = e.target.result.split('\n').filter(l => l.trim());
      const preview = document.getElementById('csv-preview');
      preview.innerHTML = `<table><thead><tr>${lines[0].split(',').map(h => `<th>${h.trim()}</th>`).join('')}</tr></thead><tbody>` +
        lines.slice(1, 11).map(line => '<tr>' + line.split(',').map(c => `<td>${c.trim()}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>' + (lines.length > 11 ? `<p style="font-size:12px;color:var(--gray-400);margin-top:8px">他 ${lines.length - 11} 件...</p>` : '');
      preview.classList.remove('hidden');
      document.getElementById('csv-actions').classList.remove('hidden');
    };
    reader.readAsText(file);
  },

  async batchCall() {
    if (!this.csvFile) return;
    const formData = new FormData();
    formData.append('file', this.csvFile);
    try {
      const res = await api('POST', '/call/batch-json', formData);
      toast(`一括架電開始: ${res.total}件`);
      this.clearCsv();
      this.refreshSessions();
    } catch (e) {
      toast('一括架電に失敗しました: ' + e.message, 'error');
    }
  },

  clearCsv() {
    this.csvFile = null;
    document.getElementById('csv-preview').classList.add('hidden');
    document.getElementById('csv-actions').classList.add('hidden');
    document.getElementById('csv-file').value = '';
  },

  async refreshSessions() {
    try {
      const sessions = await api('GET', '/sessions');
      const el = document.getElementById('call-sessions');
      const entries = Object.entries(sessions);
      if (entries.length === 0) {
        el.innerHTML = '<p style="color:var(--gray-400);font-size:14px;">通話中のセッションはありません</p>';
        return;
      }
      el.innerHTML = `<table><thead><tr><th>SID</th><th>電話番号</th><th>状態</th><th>断り返し</th><th>メッセージ数</th></tr></thead><tbody>` +
        entries.map(([sid, s]) =>
          `<tr><td style="font-family:monospace;font-size:12px">${sid.slice(0,16)}...</td><td>${s.phone_number}</td><td><span class="badge badge-info">${s.state}</span></td><td>${s.objection_count}/2</td><td>${s.message_count}</td></tr>`
        ).join('') + '</tbody></table>';
    } catch (e) { /* ignore */ }
  }
};

// ===== History =====
const History = {
  async load() {
    try {
      const status = document.getElementById('history-filter-status').value;
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      const logs = await api('GET', '/logs?' + params.toString());
      const tbody = document.getElementById('history-tbody');
      if (!logs || logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--gray-400);">データがありません</td></tr>';
        return;
      }
      tbody.innerHTML = logs.map(log => {
        const date = log.called_at ? new Date(log.called_at).toLocaleString('ja-JP') : '-';
        const statusBadge = {
          appointed: '<span class="badge badge-ok">アポ獲得</span>',
          rejected: '<span class="badge badge-ng">断り</span>',
          absent: '<span class="badge badge-warn">不在</span>',
          handoff: '<span class="badge badge-info">ハンドオフ</span>',
          in_progress: '<span class="badge badge-info">通話中</span>',
          error: '<span class="badge badge-ng">エラー</span>',
        }[log.status] || `<span class="badge">${log.status}</span>`;
        return `<tr>
          <td>${date}</td>
          <td>${log.phone_number || '-'}</td>
          <td>${log.contact_name || '-'}</td>
          <td>${statusBadge}</td>
          <td>${log.appointment_datetime || '-'}</td>
          <td><button class="btn btn-sm btn-secondary" onclick='History.showLog(${JSON.stringify(log.conversation_log || [])})'>ログ</button></td>
        </tr>`;
      }).join('');
    } catch (e) {
      toast('履歴の読み込みに失敗しました', 'error');
    }
  },

  showLog(log) {
    const body = document.getElementById('log-modal-body');
    if (!log || log.length === 0) {
      body.innerHTML = '<p style="color:var(--gray-400)">会話ログがありません</p>';
    } else {
      body.innerHTML = log.map(msg => {
        const isAI = msg.role === 'assistant';
        return `<div style="margin-bottom:12px;padding:10px;border-radius:8px;background:${isAI ? '#eef2ff' : '#f3f4f6'}">
          <div style="font-size:11px;font-weight:600;color:${isAI ? 'var(--primary)' : 'var(--gray-500)'};margin-bottom:4px">${isAI ? 'AI' : '相手'}</div>
          <div style="font-size:14px">${msg.content}</div>
        </div>`;
      }).join('');
    }
    document.getElementById('log-modal').classList.remove('hidden');
  }
};
