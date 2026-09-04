const tabsEl = document.getElementById('tabs');
const resultsEl = document.getElementById('results');
const errorEl = document.getElementById('error');
const wsBaseEl = document.getElementById('wsBase');
const langEl = document.getElementById('lang');

/** @type {Map<number, {title: string, lines: string[]}>} */
const transcripts = new Map();

function setError(msg) {
  errorEl.textContent = msg || '';
}

async function loadSettings() {
  const data = await chrome.storage.local.get({
    wsBase: 'ws://127.0.0.1:5444',
    lang: 'zh',
  });
  wsBaseEl.value = data.wsBase;
  langEl.value = data.lang;
}

async function saveSettings() {
  await chrome.storage.local.set({
    wsBase: (wsBaseEl.value || '').trim() || 'ws://127.0.0.1:5444',
    lang: langEl.value || 'zh',
  });
}

function renderResults() {
  resultsEl.innerHTML = '';
  if (transcripts.size === 0) {
    resultsEl.innerHTML = '<div class="hint">尚无转写结果</div>';
    return;
  }
  for (const [tabId, item] of transcripts.entries()) {
    const card = document.createElement('div');
    card.className = 'card';
    const h = document.createElement('h3');
    h.textContent = `#${tabId} ${item.title}`;
    const pre = document.createElement('pre');
    pre.textContent = item.lines.join('\n') || '（监听中…）';
    card.appendChild(h);
    card.appendChild(pre);
    resultsEl.appendChild(card);
  }
}

function ensureCard(tabId, title) {
  if (!transcripts.has(tabId)) {
    transcripts.set(tabId, { title: title || `Tab ${tabId}`, lines: [] });
  } else if (title) {
    transcripts.get(tabId).title = title;
  }
}

async function refreshTabs() {
  setError('');
  const res = await chrome.runtime.sendMessage({ type: 'listTabs' });
  if (!res?.ok) {
    setError(res?.error || '无法列出页签');
    return;
  }
  tabsEl.innerHTML = '';
  for (const t of res.tabs) {
    const row = document.createElement('label');
    row.className = 'tab-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = String(t.id);
    cb.checked = !!t.listening;
    const body = document.createElement('div');
    const title = document.createElement('div');
    title.textContent = t.title;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = t.url;
    const badge = document.createElement('span');
    badge.className = 'badge' + (t.listening ? ' on' : '');
    badge.textContent = t.listening ? '监听中' : (t.active ? '当前' : '页签');
    body.appendChild(title);
    body.appendChild(meta);
    body.appendChild(badge);
    row.appendChild(cb);
    row.appendChild(body);
    tabsEl.appendChild(row);
  }
  if (res.tabs.length === 0) {
    tabsEl.innerHTML = '<div class="tab-item">当前窗口没有可捕获的页签</div>';
  }
}

function selectedIds() {
  return [...tabsEl.querySelectorAll('input[type=checkbox]:checked')].map((el) => Number(el.value));
}

document.getElementById('btnRefresh').addEventListener('click', refreshTabs);

document.getElementById('btnStart').addEventListener('click', async () => {
  setError('');
  await saveSettings();
  const ids = selectedIds();
  if (ids.length === 0) {
    setError('请先勾选至少一个页签');
    return;
  }
  for (const id of ids) ensureCard(id, '');
  renderResults();
  const res = await chrome.runtime.sendMessage({ type: 'startTabs', tabIds: ids });
  if (!res) {
    setError('扩展无响应，请到 chrome://extensions 重载本扩展');
    return;
  }
  if (!res?.ok) {
    const detail = (res?.errors || []).map((e) => `#${e.tabId}: ${e.error}`).join('; ');
    const raw = detail || res?.error || '启动失败';
    // 旧版 offscreen 抢答留下的误报
    if (String(raw).includes('ignored')) {
      setError('消息通道异常（ignored）。请重载扩展后再点「开始监听所选」。');
    } else {
      setError(raw);
    }
  } else if (res.errors?.length) {
    setError(res.errors.map((e) => `#${e.tabId}: ${e.error}`).join('; '));
  } else {
    setError('');
  }
  await refreshTabs();
  renderResults();
});

document.getElementById('btnStop').addEventListener('click', async () => {
  setError('');
  await chrome.runtime.sendMessage({ type: 'stopTabs' });
  await refreshTabs();
});

document.getElementById('btnOpenPanel').addEventListener('click', async () => {
  const url = chrome.runtime.getURL('panel.html');
  await chrome.windows.create({
    url,
    type: 'popup',
    width: 900,
    height: 700,
  });
});

async function restoreTranscripts() {
  try {
    const res = await chrome.runtime.sendMessage({ type: 'getTranscripts' });
    if (!res?.ok || !res.transcripts) return;
    for (const [id, item] of Object.entries(res.transcripts)) {
      transcripts.set(Number(id), {
        title: item.title || `Tab ${id}`,
        lines: Array.isArray(item.lines) ? item.lines : [],
      });
    }
  } catch (_) {}
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'transcription' && msg.data) {
    const tabId = Number(msg.tabId ?? msg.data.tab_id);
    ensureCard(tabId, msg.title || msg.data.title);
    const item = transcripts.get(tabId);
    const line = msg.data.timestamp
      ? `[${msg.data.timestamp}] ${msg.data.text}`
      : msg.data.text;
    item.lines.push(line);
    renderResults();
    setError('');
  }
  if (msg.type === 'tabError') {
    setError(`#${msg.tabId}: ${msg.error}`);
  }
  if (msg.type === 'tabStatus' && msg.status === 'listening') {
    ensureCard(Number(msg.tabId), msg.title);
    renderResults();
    refreshTabs();
  }
  if (msg.type === 'tabStatus' && msg.status === 'streaming') {
    // 已在推音频；若长时间无字，多半是静音过滤或后端未出结果
    const el = errorEl;
    if (el && /ignored/i.test(el.textContent || '')) setError('');
  }
  if (msg.type === 'tabStatus' && msg.status === 'stopped') {
    refreshTabs();
  }
});

loadSettings()
  .then(restoreTranscripts)
  .then(refreshTabs)
  .then(renderResults);
