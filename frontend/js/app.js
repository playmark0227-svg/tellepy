/* telepy 管理画面 - メインアプリケーション */

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
  // 各モジュールの load を呼ぶ。メソッド内の this を保つためアロー関数で包む
  const loaders = {
    dashboard: () => Dashboard.load(),
    settings: () => Settings.load(),
    scripts: () => Scripts.load(),
    listbuilder: () => ListBuilder.load(),
    calls: () => Calls.load(),
    history: () => History.load(),
  };
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

// ===== List Builder =====
const ListBuilder = {
  pollTimer: null,
  currentJob: null,

  async load() {
    // ローカルCSVの設置状況を表示
    try {
      const st = await api('GET', '/list/local-status');
      const el = document.getElementById('lb-local-status');
      if (!el) return;
      if (st.configured) {
        const total = st.files.reduce((a, f) => a + f.size, 0);
        el.textContent = `ローカルCSV: ${st.files.length}ファイル検出（${st.files.map(f => f.name).join(', ')} / 計${(total / 1048576).toFixed(1)}MB）`;
        el.style.color = 'var(--success)';
      } else {
        el.textContent = `ローカルCSVなし（${st.data_dir}/ にCSVを置くとPC内検索が使えます）。未設定時はAPIまたはデモで動作します。`;
        el.style.color = 'var(--gray-400)';
      }
    } catch (e) { /* ignore */ }
  },

  fillSample() {
    document.getElementById('lb-inquiry').value =
      '工務店、不動産のリスト作成をお願いしたくお繋ぎいただきました！\n' +
      '規模感は、従業員数10-20名、資本金1000万円以下、東京と神奈川で1000件程お願いできますと幸いです。';
  },

  async testConnection() {
    const el = document.getElementById('lb-conn-status');
    el.textContent = '接続中...';
    el.style.color = 'var(--gray-400)';
    try {
      const r = await api('POST', '/list/test-connection');
      if (r.ok) {
        el.textContent = '✅ ' + r.message;
        el.style.color = 'var(--success)';
      } else {
        el.textContent = '❌ ' + r.message;
        el.style.color = 'var(--danger, #dc2626)';
      }
    } catch (e) {
      el.textContent = '❌ テスト失敗: ' + e.message;
      el.style.color = 'var(--danger, #dc2626)';
    }
  },

  async parse() {
    const text = document.getElementById('lb-inquiry').value.trim();
    if (!text) { toast('依頼文を入力してください', 'error'); return; }
    try {
      const c = await api('POST', '/list/parse', { text });
      this.fillCriteria(c);
      document.getElementById('lb-criteria-card').classList.remove('hidden');
      toast('条件を読み取りました。内容を確認してください');
    } catch (e) {
      toast('読み取りに失敗しました: ' + e.message, 'error');
    }
  },

  fillCriteria(c) {
    const yen = c.capital_max != null ? c.capital_max : '';
    document.getElementById('lb-industries').value = (c.industries || []).join(', ');
    document.getElementById('lb-prefectures').value = (c.prefectures || []).join(', ');
    document.getElementById('lb-keywords').value = (c.name_keywords || []).join(', ');
    document.getElementById('lb-emp-min').value = c.employee_min ?? '';
    document.getElementById('lb-emp-max').value = c.employee_max ?? '';
    document.getElementById('lb-cap-max').value = yen;
    document.getElementById('lb-count').value = c.target_count ?? 100;
  },

  collectCriteria() {
    const split = (id) => document.getElementById(id).value.split(',').map(s => s.trim()).filter(Boolean);
    const numOrNull = (id) => {
      const v = document.getElementById(id).value.trim();
      return v === '' ? null : parseInt(v, 10);
    };
    return {
      industries: split('lb-industries'),
      prefectures: split('lb-prefectures'),
      name_keywords: split('lb-keywords'),
      employee_min: numOrNull('lb-emp-min'),
      employee_max: numOrNull('lb-emp-max'),
      capital_max: numOrNull('lb-cap-max'),
      capital_min: null,
      target_count: numOrNull('lb-count') || 100,
    };
  },

  async build() {
    const criteria = this.collectCriteria();
    if (criteria.name_keywords.length === 0 && criteria.industries.length === 0) {
      toast('業種または社名キーワードを指定してください', 'error'); return;
    }
    const req = {
      criteria,
      mode: document.getElementById('lb-mode').value,
      enrich: document.getElementById('lb-enrich').checked,
      include_unknown_employee: document.getElementById('lb-unknown').checked,
      strict_capital: document.getElementById('lb-strict-cap').checked,
      ai_fallback: document.getElementById('lb-ai-fallback').checked,
      detail_budget: 1500,
    };
    try {
      document.getElementById('lb-result-card').classList.add('hidden');
      document.getElementById('lb-progress-card').classList.remove('hidden');
      document.getElementById('lb-progress-text').textContent = '検索を開始しています...';
      const res = await api('POST', '/list/build', req);
      this.currentJob = res.job_id;
      this.poll();
    } catch (e) {
      document.getElementById('lb-progress-card').classList.add('hidden');
      toast('リスト作成の開始に失敗しました: ' + e.message, 'error');
    }
  },

  poll() {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const tick = async () => {
      if (!this.currentJob) return;
      try {
        const job = await api('GET', '/list/jobs/' + this.currentJob);
        this.renderProgress(job);
        if (job.status === 'done') { this.renderResult(job); return; }
        if (job.status === 'error') {
          document.getElementById('lb-progress-card').classList.add('hidden');
          toast('作成に失敗しました: ' + (job.error || '不明なエラー'), 'error');
          return;
        }
        this.pollTimer = setTimeout(tick, 1500);
      } catch (e) {
        this.pollTimer = setTimeout(tick, 2500);
      }
    };
    tick();
  },

  renderProgress(job) {
    const p = job.progress || {};
    const el = document.getElementById('lb-progress-text');
    if (p.phase === 'web') {
      el.textContent = `🌐 Web探索中... ${p.found || 0} / ${p.target || '?'} 社（HP ${p.scanned || 0}件を確認 / ${p.detail || ''}）`;
    } else if (p.phase === 'collect') {
      const scanned = (p.scanned || 0).toLocaleString();
      el.textContent = `🤖 探索中... ${p.found || 0} / ${p.target || '?'} 社 収集（${scanned}社を確認 / ${p.detail || ''}）`;
    } else if (p.phase === 'local') {
      el.textContent = `PC内のCSVを検索中... ${(p.scanned || 0).toLocaleString()}行を走査 / 該当 ${p.found || 0} 社`;
    } else if (p.phase === 'search') {
      el.textContent = `検索中... 候補 ${p.found || 0} 社（${p.detail || ''}）`;
    } else if (p.phase === 'enrich') {
      const aiPart = p.ai_calls ? ` / AI確認 ${p.ai_calls} 件` : '';
      el.textContent = `🔎 HP・電話番号を無料で補完中... ${(p.found || 0).toLocaleString()} / ${(p.target || 0).toLocaleString()} 社を処理（電話取得 ${p.enriched || 0} 件${aiPart}）`;
    } else {
      el.textContent = '仕上げ中...';
    }
  },

  renderResult(job) {
    document.getElementById('lb-progress-card').classList.add('hidden');
    document.getElementById('lb-result-card').classList.remove('hidden');
    const stats = job.stats || {};
    const modeLbl = { local: 'ローカルCSV', local_web: '自前データ＋無料エンリッチ', web: 'Web自動探索', api: 'gBizINFO API', demo: 'デモ' }[job.mode] || '';
    document.getElementById('lb-result-title').textContent = `作成結果：${job.count} 社` + (modeLbl ? `（${modeLbl}）` : '');

    const statItems = [
      ['取得件数', job.count],
      ['候補総数', stats.candidates ?? '-'],
      ['詳細取得', stats.enriched ?? '-'],
      ['従業員数不明', stats.unknown_employee ?? '-'],
    ];
    // AIフォールバックを使ったモードでは、実際に叩いたAI回数（＝従量課金の実数）を表示
    if (job.mode === 'local_web') {
      statItems.push(['AI確認(有料)', stats.ai_calls ?? 0]);
    }
    document.getElementById('lb-stats').innerHTML = statItems.map(([label, val]) =>
      `<div class="stat-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
    ).join('');

    const note = document.getElementById('lb-note');
    const target = (job.progress && job.progress.target) || 0;
    const exhausted = job.progress && job.progress.exhausted;
    const isWeb = job.mode === 'web';
    const src = isWeb ? 'Web検索' : 'gBizINFO';
    const msgs = [];
    if (stats.demo) {
      msgs.push('⚠ これはデモデータです。Web自動探索を使うには検索モードを「Web自動探索」にしてください。');
    } else {
      if (exhausted && target && job.count < target) {
        msgs.push(`⚠ ${src}で見つかったのは ${job.count} 社でした（目標 ${target} 社に到達前に候補を出し切りました）。地域・業種のキーワードを増やすと件数が伸びます。`);
      } else if (target && job.count >= target) {
        msgs.push(`✅ 目標の ${target} 社に到達しました。`);
      }
      if (job.mode === 'local_web') {
        const aiCalls = stats.ai_calls || 0;
        let m = 'ℹ 自前の企業母集団（国税庁 法人番号データ等のローカルCSV）で社名・地域を絞り、無料のWeb検索で各社の公式HP・電話番号を補完しています。大半は無料で確定し、';
        m += aiCalls > 0
          ? `迷った ${aiCalls} 件だけをAI(Haiku)で確認しました（従量課金はこの件数ぶんだけ）。`
          : 'AIによる確認は発生しませんでした（＝今回は外部の従量課金ゼロ）。';
        m += '従業員数・資本金は会社概要に記載がある場合のみ取得します。';
        msgs.push(m);
      } else if (isWeb) {
        msgs.push('ℹ Web上の公開HPから会社名・電話番号・住所を抽出しています。従業員数・資本金は会社概要に記載がある場合のみ取得（無い会社は不明のまま含めます）。抽出はページ構成により取りこぼしがあります。');
      } else if ((stats.unknown_employee || 0) > 0) {
        msgs.push('ℹ 従業員数が不明な会社が含まれます（gBizINFOは小規模企業の従業員数が欠損しがち）。電話番号はgBizINFOに無いため架電用CSVの電話欄は空です。');
      }
    }
    if (msgs.length) { note.innerHTML = msgs.join('<br>'); note.classList.remove('hidden'); }
    else note.classList.add('hidden');

    const fmtYen = (v) => v == null || v === '' ? '-' : '¥' + Number(v).toLocaleString();
    document.getElementById('lb-tbody').innerHTML = (job.companies || []).map(c =>
      `<tr>
        <td>${c.name || '-'}</td>
        <td>${c.prefecture || '-'}</td>
        <td style="font-size:12px">${c.location || '-'}</td>
        <td>${fmtYen(c.capital_stock)}</td>
        <td>${c.employee_number ?? '-'}</td>
        <td style="font-size:12px">${c.industry || '-'}</td>
        <td style="font-size:12px;color:var(--gray-400)">${c.match_reason || '-'}</td>
      </tr>`
    ).join('');
  },

  download(fmt) {
    if (!this.currentJob) return;
    window.location.href = '/api/list/jobs/' + this.currentJob + '/export?fmt=' + fmt;
  }
};

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
