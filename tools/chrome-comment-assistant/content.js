/**
 * 从页面提取贴文上下文，并尝试把评论写入常见评论框。
 */

function cleanText(s) {
  return (s || '').replace(/\s+/g, ' ').trim();
}

function getSelectionText() {
  const sel = window.getSelection && window.getSelection();
  return cleanText(sel ? sel.toString() : '');
}

function pickMeta(name) {
  const el =
    document.querySelector(`meta[property="${name}"]`) ||
    document.querySelector(`meta[name="${name}"]`);
  return cleanText(el?.getAttribute('content'));
}

function extractYoutube() {
  if (!location.hostname.includes('youtube.com')) return null;
  const title =
    cleanText(document.querySelector('h1.ytd-watch-metadata yt-formatted-string')?.textContent) ||
    cleanText(document.querySelector('h1.title')?.textContent) ||
    cleanText(document.title);
  const author = cleanText(
    document.querySelector('#channel-name a')?.textContent ||
      document.querySelector('ytd-channel-name a')?.textContent
  );
  const desc =
    cleanText(document.querySelector('#description-inline-expander')?.innerText) ||
    cleanText(document.querySelector('#description')?.innerText) ||
    pickMeta('og:description');
  return {
    site: 'youtube',
    title,
    author,
    body: desc.slice(0, 2500),
  };
}

function extractBilibili() {
  if (!location.hostname.includes('bilibili.com')) return null;
  const title =
    cleanText(document.querySelector('h1.video-title')?.textContent) ||
    cleanText(document.querySelector('.video-info-title')?.textContent) ||
    cleanText(document.title);
  const author = cleanText(
    document.querySelector('.up-name')?.textContent ||
      document.querySelector('.username')?.textContent
  );
  const desc =
    cleanText(document.querySelector('.desc-info-text')?.innerText) ||
    cleanText(document.querySelector('#v_desc')?.innerText) ||
    pickMeta('description');
  return {
    site: 'bilibili',
    title,
    author,
    body: desc.slice(0, 2500),
  };
}

function extractX() {
  const host = location.hostname;
  if (!host.includes('x.com') && !host.includes('twitter.com')) return null;
  const article = document.querySelector('article[data-testid="tweet"]');
  const text = cleanText(article?.innerText || '');
  return {
    site: 'x',
    title: cleanText(document.title),
    author: '',
    body: text.slice(0, 2500),
  };
}

function extractGeneric() {
  const title = pickMeta('og:title') || cleanText(document.title);
  const body =
    pickMeta('og:description') ||
    pickMeta('description') ||
    cleanText(document.querySelector('article')?.innerText) ||
    cleanText(document.querySelector('main')?.innerText).slice(0, 2500);
  return {
    site: 'generic',
    title,
    author: '',
    body: body.slice(0, 2500),
  };
}

function extractContext() {
  const selection = getSelectionText();
  const specialized = extractYoutube() || extractBilibili() || extractX() || extractGeneric();
  return {
    ok: true,
    url: location.href,
    selection,
    title: specialized.title || '',
    author: specialized.author || '',
    body: specialized.body || '',
    site: specialized.site || 'generic',
  };
}

function setNativeValue(el, value) {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function findCommentBox() {
  const selectors = [
    '#contenteditable-root', // YouTube
    'div#contenteditable-root[contenteditable="true"]',
    'ytd-commentbox #contenteditable-root',
    'textarea.bili-comment__textarea',
    'textarea.comment-send-textarea',
    'textarea[placeholder*="评论"]',
    'textarea[placeholder*="留言"]',
    'textarea[placeholder*="说点什么"]',
    'div[contenteditable="true"][data-testid="tweetTextarea_0"]',
    'div[role="textbox"][contenteditable="true"]',
    'textarea',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    for (const el of nodes) {
      if (!(el instanceof HTMLElement)) continue;
      if (el.offsetParent === null && getComputedStyle(el).visibility === 'hidden') continue;
      // 排除搜索框等
      const ph = (el.getAttribute('placeholder') || '').toLowerCase();
      if (ph.includes('search') || ph.includes('搜索')) continue;
      return el;
    }
  }
  return null;
}

async function insertComment(text) {
  const el = findCommentBox();
  if (!el) {
    try {
      await navigator.clipboard.writeText(text);
      return { ok: true, method: 'copied' };
    } catch (_) {
      return { ok: false, error: '未找到评论框，且复制失败' };
    }
  }

  el.focus();
  if (el.isContentEditable || el.getAttribute('contenteditable') === 'true') {
    // contenteditable
    el.textContent = '';
    document.execCommand('selectAll', false, null);
    const ok = document.execCommand('insertText', false, text);
    if (!ok) {
      el.textContent = text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
    }
    return { ok: true, method: 'contenteditable' };
  }

  setNativeValue(el, text);
  return { ok: true, method: 'textarea' };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'extractContext') {
        sendResponse(extractContext());
        return;
      }
      if (msg.type === 'insertComment') {
        sendResponse(await insertComment(String(msg.text || '')));
        return;
      }
      sendResponse({ ok: false, error: 'unknown' });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});
