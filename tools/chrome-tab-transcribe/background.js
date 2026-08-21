/**
 * Service worker：协调页签列表、tabCapture streamId、offscreen 采音。
 * 实际 getUserMedia + WebSocket 在 offscreen 文档中完成。
 */

const DEFAULT_WS_BASE = 'ws://127.0.0.1:5444';

/** @type {Map<number, {title: string, url: string}>} */
const activeTabs = new Map();

async function ensureOffscreen() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
  });
  if (existing && existing.length > 0) return;
  await chrome.offscreen.createDocument({
    url: 'offscreen.html',
    reasons: ['USER_MEDIA'],
    justification: 'Capture per-tab audio for WhisprRT transcription',
  });
}

async function getSettings() {
  const data = await chrome.storage.local.get({
    wsBase: DEFAULT_WS_BASE,
    lang: 'zh',
  });
  return data;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'listTabs') {
        // panel 可能是独立 popup 窗口，currentWindow 会没有网页页签
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

            const result = await chrome.runtime.sendMessage({
              type: 'offscreenStart',
              tabId,
              streamId,
              wsUrl,
              title,
            });
            if (result && result.ok === false) {
              throw new Error(result.error || 'offscreen start failed');
            }
            activeTabs.set(tabId, { title, url: tab.url || '' });
            started.push(tabId);
          } catch (e) {
            errors.push({ tabId, error: String(e?.message || e) });
          }
        }
        sendResponse({ ok: errors.length === 0, started, errors, activeIds: [...activeTabs.keys()] });
        return;
      }

      if (msg.type === 'stopTabs') {
        const ids = Array.isArray(msg.tabIds)
          ? msg.tabIds.map(Number)
          : [...activeTabs.keys()];
        await ensureOffscreen();
        for (const tabId of ids) {
          try {
            await chrome.runtime.sendMessage({ type: 'offscreenStop', tabId });
          } catch (_) {
            /* ignore */
          }
          activeTabs.delete(tabId);
        }
        if (activeTabs.size === 0) {
          try {
            await chrome.offscreen.closeDocument();
          } catch (_) {
            /* ignore */
          }
        }
        sendResponse({ ok: true, activeIds: [...activeTabs.keys()] });
        return;
      }

      if (msg.type === 'transcription' || msg.type === 'tabStatus' || msg.type === 'tabError') {
        // 转发给所有扩展页（panel / popup）
        chrome.runtime.sendMessage(msg).catch(() => {});
        if (msg.type === 'tabStatus' && msg.status === 'stopped') {
          activeTabs.delete(Number(msg.tabId));
        }
        sendResponse({ ok: true });
        return;
      }

      sendResponse({ ok: false, error: 'unknown message' });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  console.log('WhisprRT 多页签听写已安装');
});
