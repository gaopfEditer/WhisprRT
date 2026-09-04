/**
 * Service worker：协调页签列表、tabCapture streamId、offscreen 采音。
 * 实际 getUserMedia + WebSocket 在 offscreen 文档中完成。
 */

const DEFAULT_WS_BASE = 'ws://127.0.0.1:5444';

/** @type {Map<number, {title: string, url: string}>} */
const activeTabs = new Map();

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function ensureOffscreen() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
  });
  if (existing && existing.length > 0) {
    // 确认 listener 已就绪
    try {
      const ping = await chrome.runtime.sendMessage({ type: 'offscreenPing' });
      if (ping?.ok) return;
    } catch (_) {
      /* recreate below */
    }
    try {
      await chrome.offscreen.closeDocument();
    } catch (_) {}
  }
  await chrome.offscreen.createDocument({
    url: 'offscreen.html',
    reasons: ['USER_MEDIA', 'AUDIO_PLAYBACK'],
    justification: 'Capture per-tab audio for WhisprRT transcription and play it back',
  });
  // 等待 offscreen 脚本注册 onMessage
  for (let i = 0; i < 20; i++) {
    await sleep(50);
    try {
      const ping = await chrome.runtime.sendMessage({ type: 'offscreenPing' });
      if (ping?.ok) return;
    } catch (_) {}
  }
  throw new Error('Offscreen 文档未能就绪，请重载扩展后再试');
}

async function getSettings() {
  const data = await chrome.storage.local.get({
    wsBase: DEFAULT_WS_BASE,
    lang: 'zh',
  });
  return data;
}

async function callOffscreen(message) {
  await ensureOffscreen();
  const result = await chrome.runtime.sendMessage(message);
  if (!result) {
    throw new Error('Offscreen 无响应，请重载扩展');
  }
  if (result.ok === false) {
    throw new Error(result.error || 'offscreen failed');
  }
  return result;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // offscreen 专用消息：由 offscreen.js 应答，SW 绝不抢答
  if (
    msg?.type === 'offscreenPing' ||
    msg?.type === 'offscreenStart' ||
    msg?.type === 'offscreenStop'
  ) {
    return false;
  }

  // offscreen / 其它扩展页广播的状态：更新 SW 状态并落盘；UI 自己也会直接收到同一条消息，不再二次转发（避免重复行）
  if (msg?.type === 'transcription' || msg?.type === 'tabStatus' || msg?.type === 'tabError') {
    if (msg.__forwarded) {
      return false;
    }
    if (msg.type === 'tabStatus' && msg.status === 'stopped') {
      activeTabs.delete(Number(msg.tabId));
    }
    if (msg.type === 'transcription' && msg.data) {
      const tabId = String(msg.tabId ?? msg.data.tab_id);
      chrome.storage.session.get({ transcripts: {} }).then((data) => {
        const all = data.transcripts || {};
        const prev = all[tabId] || { title: msg.title || '', lines: [] };
        const line = msg.data.timestamp
          ? `[${msg.data.timestamp}] ${msg.data.text}`
          : msg.data.text;
        prev.title = msg.title || msg.data.title || prev.title;
        prev.lines = [...(prev.lines || []), line].slice(-200);
        all[tabId] = prev;
        chrome.storage.session.set({ transcripts: all });
      });
    }
    return false;
  }

  (async () => {
    try {
      if (msg.type === 'listTabs') {
        let tabs = await chrome.tabs.query({ lastFocusedWindow: true });
        const usable = (list) =>
          list.filter(
            (t) =>
              t.id != null &&
              t.url &&
              !t.url.startsWith('chrome://') &&
              !t.url.startsWith('chrome-extension://') &&
              !t.url.startsWith('edge://')
          );
        let filtered = usable(tabs);
        if (filtered.length === 0) {
          tabs = await chrome.tabs.query({});
          filtered = usable(tabs);
        }
        sendResponse({
          ok: true,
          tabs: filtered.map((t) => ({
            id: t.id,
            title: t.title || `Tab ${t.id}`,
            url: t.url || '',
            active: !!t.active,
            listening: activeTabs.has(t.id),
          })),
          activeIds: [...activeTabs.keys()],
        });
        return;
      }

      if (msg.type === 'getActive') {
        sendResponse({ ok: true, activeIds: [...activeTabs.keys()] });
        return;
      }

      if (msg.type === 'getTranscripts') {
        const data = await chrome.storage.session.get({ transcripts: {} });
        sendResponse({ ok: true, transcripts: data.transcripts || {} });
        return;
      }

      if (msg.type === 'clearTranscripts') {
        await chrome.storage.session.set({ transcripts: {} });
        sendResponse({ ok: true });
        return;
      }

      if (msg.type === 'startTabs') {
        const ids = Array.isArray(msg.tabIds) ? msg.tabIds.map(Number) : [];
        const settings = await getSettings();
        await ensureOffscreen();
        const started = [];
        const errors = [];

        for (const tabId of ids) {
          if (activeTabs.has(tabId)) {
            started.push(tabId);
            continue;
          }
          try {
            const tab = await chrome.tabs.get(tabId);
            const streamId = await chrome.tabCapture.getMediaStreamId({
              targetTabId: tabId,
            });
            const title = tab.title || `Tab ${tabId}`;
            const wsUrl =
              `${settings.wsBase.replace(/\/$/, '')}/ws/tab` +
              `?tab_id=${encodeURIComponent(String(tabId))}` +
              `&title=${encodeURIComponent(title)}` +
              `&lang=${encodeURIComponent(settings.lang || 'zh')}`;

            await callOffscreen({
              type: 'offscreenStart',
              tabId,
              streamId,
              wsUrl,
              title,
            });
            activeTabs.set(tabId, { title, url: tab.url || '' });
            started.push(tabId);
          } catch (e) {
            errors.push({ tabId, error: String(e?.message || e) });
          }
        }
        sendResponse({
          ok: errors.length === 0,
          started,
          errors,
          activeIds: [...activeTabs.keys()],
        });
        return;
      }

      if (msg.type === 'stopTabs') {
        const ids = Array.isArray(msg.tabIds)
          ? msg.tabIds.map(Number)
          : [...activeTabs.keys()];
        for (const tabId of ids) {
          try {
            await callOffscreen({ type: 'offscreenStop', tabId });
          } catch (_) {
            /* ignore */
          }
          activeTabs.delete(tabId);
        }
        if (activeTabs.size === 0) {
          try {
            await chrome.offscreen.closeDocument();
          } catch (_) {}
        }
        sendResponse({ ok: true, activeIds: [...activeTabs.keys()] });
        return;
      }

      sendResponse({ ok: false, error: `unknown message: ${msg?.type}` });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  console.log('WhisprRT 多页签听写已安装');
});
