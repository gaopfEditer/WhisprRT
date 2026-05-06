// content.js - 在视频列表页面注入选择按钮
(function() {
  'use strict';

  const SELECTOR_BUTTON_ID = 'whispr-select-btn';
  const STORAGE_KEY = 'selectedVideos';
  const POD_BULK_BAR_CLASS = 'whispr-pod-bulk-bar';
  const PAGE_BULK_BAR_ID = 'whispr-page-bulk-bar';

  // 检查是否为视频列表页面
  function isVideoListPage() {
    const url = window.location.href;
    // B站：搜索页、分区页、用户主页等
    if (url.includes('bilibili.com')) {
      return !url.includes('/video/BV') || url.includes('/search');
    }
    // YouTube：首页、搜索结果、频道页等
    if (url.includes('youtube.com')) {
      return !url.includes('/watch?v=');
    }
    return false;
  }

  // 获取视频信息
  function getVideoInfo(element) {
    const url = window.location.href;
    
    if (url.includes('bilibili.com')) {
      return getBilibiliVideoInfo(element);
    } else if (url.includes('youtube.com')) {
      return getYouTubeVideoInfo(element);
    }
    return null;
  }

  // 合集 / 选集侧栏：.video-pod__list 内子项带 data-key（BV…），无独立 a 链接
  function extractVideoPodItemTitle(element) {
    const titleTxt = element.querySelector('.title-txt');
    if (titleTxt) {
      const t = (titleTxt.textContent || '').replace(/\s+/g, ' ').trim();
      if (t) return t;
    }
    const titleWrap = element.querySelector('.title');
    if (titleWrap) {
      const fromAttr = (titleWrap.getAttribute('title') || '').trim();
      if (fromAttr) return fromAttr;
      const t = (titleWrap.textContent || '').replace(/\s+/g, ' ').trim();
      if (t && !/^\d{1,2}:\d{2}$/.test(t)) return t;
    }
    return '';
  }

  function bilibiliUrlFromDataKey(raw) {
    if (!raw) return null;
    const id = String(raw).trim();
    if (/^BV[\w]+$/i.test(id)) return `https://www.bilibili.com/video/${id}`;
    if (/^av\d+$/i.test(id)) return `https://www.bilibili.com/video/${id.toLowerCase()}`;
    return null;
  }

  // 获取B站视频信息
  function getBilibiliVideoInfo(element) {
    try {
      const dataKey = element.getAttribute && element.getAttribute('data-key');
      const fromKey = bilibiliUrlFromDataKey(dataKey);
      if (fromKey) {
        let title = extractVideoPodItemTitle(element);
        if (!title) title = extractBilibiliTitle(element, null);
        return {
          title: (title && title.trim()) ? title.trim() : '未知标题',
          link: fromKey,
          element: element
        };
      }

      // 创作中心 / 推荐区：封面 a.bili-cover-card（href 常为 //www.bilibili.com/video/BV…）
      let linkElement = element.querySelector(
        'a.bili-cover-card[href*="/video/BV"], a.bili-cover-card[href*="/video/bv"], a.bili-cover-card[href*="/video/av"], a.bili-cover-card[href*="/video/AV"], a.bili-cover-card[href*="//www.bilibili.com/video/"], a.bili-cover-card[href*="//m.bilibili.com/video/"]'
      );
      if (!linkElement) {
        linkElement = element.querySelector(
          'a[href*="/video/BV"], a[href*="/video/bv"], a[href*="/video/av"], a[href*="/video/AV"], a[href*="//www.bilibili.com/video/"], a[href*="//m.bilibili.com/video/"]'
        );
      }
      if (!linkElement) {
        const allLinks = element.querySelectorAll('a');
        for (const link of allLinks) {
          const href = link.getAttribute('href') || '';
          if (
            href.includes('/video/BV') ||
            href.includes('/video/bv') ||
            href.includes('/video/av') ||
            href.includes('/video/AV') ||
            href.includes('//www.bilibili.com/video/') ||
            href.includes('//m.bilibili.com/video/')
          ) {
            linkElement = link;
            break;
          }
        }
      }
      if (!linkElement) {
        return null;
      }

      let href = linkElement.getAttribute('href') || '';
      if (!href) return null;

      if (href.startsWith('//')) {
        href = 'https:' + href;
      } else if (href.startsWith('/')) {
        href = 'https://www.bilibili.com' + href;
      } else if (!href.startsWith('http')) {
        href = 'https://www.bilibili.com/' + href;
      }

      const bvMatch = href.match(/\/video\/(BV[\w]+)/);
      const avMatch = href.match(/\/video\/(av\d+)/i);
      if (!bvMatch && !avMatch) return null;

      const videoId = bvMatch ? bvMatch[1] : avMatch[1];
      const fullUrl = `https://www.bilibili.com/video/${videoId}`;
      const title = extractBilibiliTitle(element, linkElement);

      return {
        title: (title && title.trim()) ? title.trim() : '未知标题',
        link: fullUrl,
        element: element
      };
    } catch (e) {
      console.error('[B站] 提取视频信息出错:', e);
      return null;
    }
  }

  // 提取B站标题（按结构：.bili-video-card__title[title] 或 .bili-video-card__title > a 文本）
  function extractBilibiliTitle(element, linkElement) {
    const reject = (t) => !t || !t.trim() || t.includes('添加至') || t.includes('稍后再看') || /^\d+[.\d]*[万千]?\s*[\d:]+$/.test(t);

    // 1) 按你提供的结构：.bili-video-card__title 的 title 属性
    const titleEl = element.querySelector('.bili-video-card__title');
    if (titleEl) {
      let t = titleEl.getAttribute('title');
      if (t && !reject(t)) return t.trim();
      const innerA = titleEl.querySelector('a');
      t = (innerA && (innerA.textContent || innerA.innerText)) ? (innerA.textContent || innerA.innerText).replace(/\s+/g, ' ').trim() : '';
      if (t && !reject(t)) return t;
      t = (titleEl.textContent || titleEl.innerText || '').replace(/\s+/g, ' ').trim();
      if (t && !reject(t)) return t;
    }

    // 1b) 封面区：a.bili-cover-card 的 title，或封面图 alt（与标题区一致时常用作无障碍文案）
    const coverA = element.querySelector('a.bili-cover-card[href*="/video/"]');
    if (coverA) {
      let t = (coverA.getAttribute('title') || '').trim();
      if (t && !reject(t)) return t;
    }
    const coverImg = element.querySelector('a.bili-cover-card img[alt], .bili-cover-card__thumbnail img[alt]');
    if (coverImg) {
      const t = (coverImg.getAttribute('alt') || '').trim();
      if (t && !reject(t)) return t;
    }

    // 2) 任意 [class*="title"]
    for (const el of element.querySelectorAll('[class*="title"]')) {
      const t = (el.getAttribute('title') || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!reject(t) && t.length > 2) return t;
    }

    // 3) 链接的 title（如 a.bili-cover-card 的 title）
    if (linkElement) {
      const t = (linkElement.getAttribute('title') || '').trim();
      if (!reject(t)) return t;
    }

    // 4) 卡片内第一段较长文本
    for (const node of element.querySelectorAll('a, span, p, div[class*="desc"], div[class*="info"]')) {
      const t = (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length >= 3 && t.length <= 120 && !reject(t) && !/^[\d:\s]+$/.test(t)) return t;
    }
    return '';
  }

  // 获取YouTube视频信息
  function getYouTubeVideoInfo(element) {
    try {
      // 查找视频链接
      let linkElement = element.querySelector('a[href*="/watch?v="], a[href*="/shorts/"]');
      
      // 如果没有找到，尝试在子元素中查找
      if (!linkElement) {
        const allLinks = element.querySelectorAll('a');
        for (const link of allLinks) {
          const href = link.getAttribute('href') || '';
          if (href.includes('/watch?v=') || href.includes('/shorts/')) {
            linkElement = link;
            break;
          }
        }
      }

      if (!linkElement) return null;

      const href = linkElement.getAttribute('href');
      let fullUrl = href;
      if (href.startsWith('/')) {
        fullUrl = `https://www.youtube.com${href}`;
      }
      
      // 提取视频ID
      const videoIdMatch = fullUrl.match(/[?&]v=([^&]+)/) || fullUrl.match(/\/shorts\/([^?&]+)/);
      if (videoIdMatch) {
        fullUrl = `https://www.youtube.com/watch?v=${videoIdMatch[1]}`;
      }

      // 提取标题
      const title = extractYouTubeTitle(element, linkElement);

      return {
        title: title.trim() || '未知标题',
        link: fullUrl.split('&')[0], // 移除额外参数
        element: element
      };
    } catch (e) {
      console.error('Error extracting YouTube video info:', e);
      return null;
    }
  }

  // 提取YouTube标题
  function extractYouTubeTitle(element, linkElement) {
    // 过滤掉明显不是标题的内容
    function isValidTitle(text) {
      if (!text || !text.trim()) return false;
      
      // 过滤掉时间格式（如 "15:44"、"15:44 15:44"）
      if (text.match(/^\d{1,2}:\d{2}(\s+\d{1,2}:\d{2})*$/)) return false;
      
      // 过滤掉"正在播放"等播放器状态文本
      if (text.includes('正在播放') || text.includes('正在播放中')) return false;
      if (text.includes('Playing') || text.includes('Paused')) return false;
      
      // 过滤掉只有时间戳的文本
      if (text.trim().match(/^[\d:\s]+$/)) return false;
      
      // 过滤掉包含时长信息的文本（如 "14分钟23秒钟"）
      if (text.match(/\d+\s*(分钟|秒钟|小时|分|秒|时)/)) {
        // 如果整个文本就是时长，则无效
        if (text.trim().match(/^\d+\s*(分钟|秒钟|小时|分|秒|时)/)) return false;
      }
      
      // 标题应该有一定长度（至少3个字符）
      if (text.trim().length < 3) return false;
      
      return true;
    }

    // 最优先：直接查找 #video-title 元素（这是YouTube的标准标题元素）
    const videoTitleElement = element.querySelector('#video-title');
    if (videoTitleElement) {
      // 优先使用 title 属性（最准确，不包含时长等信息）
      let title = videoTitleElement.getAttribute('title');
      if (title && isValidTitle(title)) {
        return title.trim();
      }
      
      // 如果没有 title 属性，使用文本内容
      title = videoTitleElement.textContent || videoTitleElement.innerText;
      if (title && isValidTitle(title)) {
        // 清理文本：移除可能的时长信息（如 "14分钟23秒钟"）
        title = title.replace(/\s*\d+\s*(分钟|秒钟|小时|分|秒|时).*$/, '').trim();
        if (isValidTitle(title)) {
          return title;
        }
      }
    }

    // 其次：从链接元素的title属性获取
    if (linkElement) {
      let title = linkElement.getAttribute('title');
      if (title && isValidTitle(title)) {
        return title.trim();
      }

      // 从链接元素的文本内容获取
      title = linkElement.textContent || linkElement.innerText;
      if (title && isValidTitle(title)) {
        // 清理文本：移除可能的时长信息
        title = title.replace(/\s*\d+\s*(分钟|秒钟|小时|分|秒|时).*$/, '').trim();
        if (isValidTitle(title)) {
          return title;
        }
      }
    }

    // 备用选择器
    const titleSelectors = [
      '#video-title-link',
      'ytd-video-meta-block #video-title',
      'ytd-video-meta-block #video-title-link',
      'h3.ytd-video-meta-block a',
      'h3.ytd-video-meta-block',
      'h3 a[id*="title"]',
      'h3 a[class*="title"]',
      'h3 a'
    ];

    for (const selector of titleSelectors) {
      const titleElement = element.querySelector(selector);
      if (titleElement) {
        // 优先使用 title 属性
        let title = titleElement.getAttribute('title');
        if (title && isValidTitle(title)) {
          return title.trim();
        }
        
        // 如果没有 title 属性，使用文本内容
        title = titleElement.textContent || titleElement.innerText;
        if (title && isValidTitle(title)) {
          // 清理文本：移除可能的时长信息
          title = title.replace(/\s*\d+\s*(分钟|秒钟|小时|分|秒|时).*$/, '').trim();
          if (isValidTitle(title)) {
            return title;
          }
        }
      }
    }

    return '';
  }

  // 创建选择按钮
  function createSelectButton(videoInfo) {
    const button = document.createElement('div');
    button.className = SELECTOR_BUTTON_ID;
    button.innerHTML = '✓';
    button.title = '点击选择/取消选择此视频';
    
    // 样式
    Object.assign(button.style, {
      position: 'absolute',
      top: '8px',
      left: '8px',
      width: '28px',
      height: '28px',
      borderRadius: '50%',
      backgroundColor: '#4CAF50',
      color: 'white',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      fontSize: '16px',
      fontWeight: 'bold',
      zIndex: '10000',
      boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
      transition: 'all 0.2s',
      userSelect: 'none'
    });

    // 悬停效果
    button.addEventListener('mouseenter', () => {
      button.style.transform = 'scale(1.1)';
      button.style.backgroundColor = '#45a049';
    });
    button.addEventListener('mouseleave', () => {
      if (!button.classList.contains('selected')) {
        button.style.transform = 'scale(1)';
        button.style.backgroundColor = '#4CAF50';
      }
    });

    // 点击事件
    button.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      await toggleVideoSelection(videoInfo, button);
    });

    return button;
  }

  // 切换视频选择状态
  async function toggleVideoSelection(videoInfo, button) {
    try {
      const result = await chrome.storage.local.get([STORAGE_KEY]);
      const selectedVideos = result[STORAGE_KEY] || [];
      
      // 检查是否已选择
      const index = selectedVideos.findIndex(v => v.link === videoInfo.link);
      
      if (index >= 0) {
        // 取消选择
        selectedVideos.splice(index, 1);
        button.classList.remove('selected');
        button.style.backgroundColor = '#4CAF50';
        button.innerHTML = '✓';
      } else {
        // 选择
        selectedVideos.push({
          title: videoInfo.title,
          link: videoInfo.link,
          selectedAt: Date.now()
        });
        button.classList.add('selected');
        button.style.backgroundColor = '#2196F3';
        button.innerHTML = '✓';
      }

      // 保存到storage
      await chrome.storage.local.set({ [STORAGE_KEY]: selectedVideos });
      
      // 通知popup更新
      chrome.runtime.sendMessage({ action: 'selectionChanged' });
    } catch (error) {
      console.error('Error toggling selection:', error);
    }
  }

  // 更新按钮状态
  async function updateButtonState(button, videoInfo) {
    try {
      const result = await chrome.storage.local.get([STORAGE_KEY]);
      const selectedVideos = result[STORAGE_KEY] || [];
      const isSelected = selectedVideos.some(v => v.link === videoInfo.link);
      
      if (isSelected) {
        button.classList.add('selected');
        button.style.backgroundColor = '#2196F3';
      } else {
        button.classList.remove('selected');
        button.style.backgroundColor = '#4CAF50';
      }
    } catch (error) {
      console.error('Error updating button state:', error);
    }
  }

  async function refreshAllSelectButtons() {
    const buttons = document.querySelectorAll(`.${SELECTOR_BUTTON_ID}`);
    for (const btn of buttons) {
      const item = btn.parentElement;
      if (!item) continue;
      const info = getVideoInfo(item);
      if (info) await updateButtonState(btn, info);
    }
  }

  /** 某一 .video-pod__list（含 .video-list 下）内条目全选 / 全不选 */
  async function setPodListSelection(podListRoot, selectAll) {
    const items = podListRoot.querySelectorAll('[data-key]');
    const result = await chrome.storage.local.get([STORAGE_KEY]);
    let selectedVideos = result[STORAGE_KEY] || [];
    const linksInList = new Set();

    const toMerge = [];
    items.forEach((el) => {
      const info = getBilibiliVideoInfo(el);
      if (!info || !info.link) return;
      linksInList.add(info.link);
      if (selectAll) {
        toMerge.push({ title: info.title, link: info.link, selectedAt: Date.now() });
      }
    });

    if (selectAll) {
      const byLink = new Map(selectedVideos.map((v) => [v.link, v]));
      toMerge.forEach((v) => byLink.set(v.link, v));
      selectedVideos = Array.from(byLink.values());
    } else {
      selectedVideos = selectedVideos.filter((v) => !linksInList.has(v.link));
    }

    await chrome.storage.local.set({ [STORAGE_KEY]: selectedVideos });
    try {
      chrome.runtime.sendMessage({ action: 'selectionChanged' });
    } catch (e) { /* popup 未打开时无接收端 */ }

    for (const el of items) {
      const btn = el.querySelector(`.${SELECTOR_BUTTON_ID}`);
      if (!btn) continue;
      const info = getBilibiliVideoInfo(el);
      if (info) await updateButtonState(btn, info);
    }
  }

  /** 当前页上所有已挂载 ✓ 的条目：本页全选 / 本页取消（含选集 + 卡片等） */
  async function setPageSelection(selectAll) {
    const buttons = document.querySelectorAll(`.${SELECTOR_BUTTON_ID}`);
    const result = await chrome.storage.local.get([STORAGE_KEY]);
    let selectedVideos = result[STORAGE_KEY] || [];
    const pageLinks = new Set();

    buttons.forEach((btn) => {
      const item = btn.parentElement;
      const info = item && getVideoInfo(item);
      if (info && info.link) pageLinks.add(info.link);
    });

    if (selectAll) {
      const byLink = new Map(selectedVideos.map((v) => [v.link, v]));
      buttons.forEach((btn) => {
        const item = btn.parentElement;
        const info = item && getVideoInfo(item);
        if (info && info.link) {
          byLink.set(info.link, { title: info.title, link: info.link, selectedAt: Date.now() });
        }
      });
      selectedVideos = Array.from(byLink.values());
    } else {
      selectedVideos = selectedVideos.filter((v) => !pageLinks.has(v.link));
    }

    await chrome.storage.local.set({ [STORAGE_KEY]: selectedVideos });
    try {
      chrome.runtime.sendMessage({ action: 'selectionChanged' });
    } catch (e) { /* ignore */ }

    await refreshAllSelectButtons();
  }

  function styleWhisprMiniButton(btn) {
    Object.assign(btn.style, {
      padding: '4px 10px',
      fontSize: '12px',
      border: '1px solid #ccc',
      borderRadius: '4px',
      background: '#fff',
      cursor: 'pointer',
      color: '#333'
    });
    btn.addEventListener('mouseenter', () => {
      btn.style.background = '#f0f0f0';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.background = '#fff';
    });
  }

  /** 每个 .video-pod__list 顶部一条：全选本列表 / 取消本列表（含 video-list 下嵌套） */
  function ensurePodBulkBars() {
    if (!location.href.includes('bilibili.com')) return;

    document.querySelectorAll('.video-pod__list').forEach((podList) => {
      if (podList.querySelector(`:scope > .${POD_BULK_BAR_CLASS}`)) return;

      const bar = document.createElement('div');
      bar.className = POD_BULK_BAR_CLASS;
      Object.assign(bar.style, {
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: '8px',
        padding: '6px 8px',
        marginBottom: '6px',
        background: 'rgba(0, 180, 120, 0.08)',
        borderRadius: '6px',
        border: '1px solid rgba(0, 150, 100, 0.2)',
        fontSize: '12px',
        color: '#333',
        position: 'relative',
        zIndex: '10001'
      });

      const label = document.createElement('span');
      label.textContent = '选集列表';
      label.style.cssText = 'color:#666;margin-right:4px;user-select:none';

      const btnAll = document.createElement('button');
      btnAll.type = 'button';
      btnAll.textContent = '全选本列表';
      styleWhisprMiniButton(btnAll);
      btnAll.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        await setPodListSelection(podList, true);
      });

      const btnNone = document.createElement('button');
      btnNone.type = 'button';
      btnNone.textContent = '取消本列表';
      styleWhisprMiniButton(btnNone);
      btnNone.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        await setPodListSelection(podList, false);
      });

      bar.append(label, btnAll, btnNone);
      podList.insertBefore(bar, podList.firstChild);
    });
  }

  /** 右下角：本页全选 / 本页取消 */
  function ensurePageBulkBar() {
    if (!location.href.includes('bilibili.com')) return;
    if (document.getElementById(PAGE_BULK_BAR_ID)) return;

    const bar = document.createElement('div');
    bar.id = PAGE_BULK_BAR_ID;
    Object.assign(bar.style, {
      position: 'fixed',
      right: '12px',
      bottom: '72px',
      zIndex: '100002',
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      padding: '8px 10px',
      background: 'rgba(255,255,255,0.96)',
      border: '1px solid #ddd',
      borderRadius: '8px',
      boxShadow: '0 2px 12px rgba(0,0,0,0.12)',
      fontSize: '12px',
      color: '#333'
    });

    const title = document.createElement('div');
    title.textContent = '文字稿助手';
    title.style.cssText = 'font-weight:600;color:#444;margin-bottom:2px;user-select:none';

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap';

    const btnPageAll = document.createElement('button');
    btnPageAll.type = 'button';
    btnPageAll.textContent = '本页全选';
    styleWhisprMiniButton(btnPageAll);
    btnPageAll.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await setPageSelection(true);
    });

    const btnPageNone = document.createElement('button');
    btnPageNone.type = 'button';
    btnPageNone.textContent = '本页取消';
    styleWhisprMiniButton(btnPageNone);
    btnPageNone.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await setPageSelection(false);
    });

    row.append(btnPageAll, btnPageNone);
    bar.append(title, row);
    document.body.appendChild(bar);
  }

  // 获取 B 站视频卡片容器（合并：选集 .video-pod__list + 卡片 .bili-video-card*，按 canonical 视频 URL 去重）
  function getBilibiliVideoContainers() {
    const seenLink = new Set();
    const list = [];

    function consider(el) {
      if (!el || el.nodeType !== 1) return;
      if (el.querySelector(`.${SELECTOR_BUTTON_ID}`)) return;
      const info = getBilibiliVideoInfo(el);
      if (!info || !info.link) return;
      if (seenLink.has(info.link)) return;
      seenLink.add(info.link);
      list.push(el);
    }

    document.querySelectorAll('.video-pod__list [data-key]').forEach(consider);
    document.querySelectorAll('.bili-video-card__wrap').forEach(consider);
    document.querySelectorAll('.bili-video-card').forEach(consider);
    document.querySelectorAll('.upload-video-card__left').forEach(consider);

    if (list.length > 0) {
      return list;
    }

    const knownSelectors = [
      '[class*="bili-video-card__wrap"]',
      '[class*="bili-video-card"]',
      '.video-card',
      '.feed-card',
      '[class*="feed-card"]'
    ];
    for (const sel of knownSelectors) {
      try {
        document.querySelectorAll(sel).forEach(consider);
      } catch (e) { /* 忽略无效选择器 */ }
    }
    if (list.length > 0) return list;

    document.querySelectorAll(
      'a[href*="/video/BV"], a[href*="/video/bv"], a[href*="/video/av"], a[href*="/video/AV"], a[href*="//www.bilibili.com/video/"], a[href*="//m.bilibili.com/video/"]'
    ).forEach((link) => {
      const hrefRaw = link.getAttribute('href') || '';
      if (!hrefRaw.includes('/video/')) return;

      let container = link.closest('.bili-video-card__wrap, .bili-video-card, .upload-video-card__left, [class*="bili-video-card"], .video-card, .feed-card');
      if (!container) {
        container = link.closest('li, div[class*="card"], div[class*="item"], article, section');
      }
      if (!container) {
        container = link.closest('div[class*="cover"], div[class*="info"]')?.parentElement || link.parentElement?.parentElement;
      }
      if (container && container !== document.body) {
        consider(container);
      }
    });
    return list;
  }

  // 为视频项添加选择按钮
  function addButtonsToVideos() {
    const url = window.location.href;
    let videoItems = [];

    if (url.includes('bilibili.com')) {
      videoItems = getBilibiliVideoContainers();
      console.log(`[B站] 找到 ${videoItems.length} 个视频卡片`);
    } else if (url.includes('youtube.com')) {
      // YouTube视频列表选择器
      videoItems = document.querySelectorAll(
        'ytd-video-renderer, ytd-grid-video-renderer, ytd-playlist-video-renderer, ' +
        'ytd-compact-video-renderer, ytd-rich-item-renderer, ytd-video-renderer'
      );
    }

    let addedCount = 0;
    let skippedCount = 0;
    let failedCount = 0;

    videoItems.forEach((item, index) => {
      // 检查是否已经添加过按钮
      if (item.querySelector(`.${SELECTOR_BUTTON_ID}`)) {
        skippedCount++;
        return;
      }

      const videoInfo = getVideoInfo(item);
      if (!videoInfo) {
        failedCount++;
        if (url.includes('bilibili.com') && index < 3) {
          // 只打印前3个失败的情况，避免日志过多
          console.log(`[B站调试] 第 ${index + 1} 个元素无法提取视频信息:`, item);
        }
        return;
      }

      // 确保父元素有相对定位
      const parent = item.closest('div, li, article');
      if (parent) {
        const computedStyle = window.getComputedStyle(parent);
        if (computedStyle.position === 'static') {
          parent.style.position = 'relative';
        }
      }

      // 创建并添加按钮
      const button = createSelectButton(videoInfo);
      item.style.position = 'relative';
      item.appendChild(button);

      // 更新按钮状态
      updateButtonState(button, videoInfo);
      addedCount++;
      
      if (url.includes('bilibili.com') && index < 3) {
        console.log(`[B站调试] 成功添加按钮 ${index + 1}:`, {
          title: videoInfo.title,
          link: videoInfo.link
        });
      }
    });

    // 调试信息
    if (url.includes('bilibili.com')) {
      console.log(`[B站调试] 总计: 找到 ${videoItems.length} 个视频项，添加了 ${addedCount} 个按钮，跳过 ${skippedCount} 个，失败 ${failedCount} 个`);
      ensurePodBulkBars();
      ensurePageBulkBar();
    }
  }

  // 初始化
  function init() {
    console.log('[B站调试] Content Script 初始化，当前URL:', location.href);
    
    // 对于B站，需要等待更长时间，因为内容可能是动态加载的
    const delay = location.href.includes('bilibili.com') ? 1500 : 500;
    
    setTimeout(() => {
      console.log('[B站调试] 开始添加按钮...');
      addButtonsToVideos();
    }, delay);

    // 监听DOM变化（处理动态加载的内容）
    let addButtonsTimeout;
    const observer = new MutationObserver((mutations) => {
      // 检查是否有新的视频卡片添加
      const hasNewVideoCards = mutations.some(mutation => {
        return Array.from(mutation.addedNodes).some(node => {
          if (node.nodeType !== 1) return false;
          const el = node.nodeType === 1 ? node : node.parentElement;
          if (!el || !el.querySelector) return false;
          return el.matches?.('.bili-video-card__wrap, .bili-video-card, .upload-video-card__left, [class*="bili-video-card"], .video-card, .feed-card, [class*="feed-card"], .video-pod__list, .video-pod__item, [class*="video-pod"], .video-list, [class*="video-list"]') ||
            el.querySelector('a[href*="/video/BV"], a[href*="/video/av"], .video-pod__list [data-key]');
        });
      });

      if (hasNewVideoCards || location.href.includes('bilibili.com')) {
        // 防抖：避免频繁执行
        clearTimeout(addButtonsTimeout);
        addButtonsTimeout = setTimeout(() => {
          addButtonsToVideos();
        }, 500);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    // 监听URL变化（SPA应用）
    let lastUrl = location.href;
    const urlObserver = new MutationObserver(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        console.log('[B站调试] URL变化，重新添加按钮:', location.href);
        setTimeout(() => {
          addButtonsToVideos();
        }, 1500); // B站需要更长的延迟
      }
    });

    urlObserver.observe(document, { subtree: true, childList: true });

    // 对于B站，额外监听滚动事件（因为B站很多内容是通过滚动加载的）
    if (location.href.includes('bilibili.com')) {
      let scrollTimeout;
      window.addEventListener('scroll', () => {
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
          addButtonsToVideos();
        }, 800);
      });
    }

    console.log('视频转文字稿助手 - Content Script 已加载', location.href);
  }

  /** 解析当前页所有 .video-pod__list 下的合集条目（标题 + 完整视频 URL） */
  function scrapeBilibiliVideoPodLists() {
    const out = [];
    const seen = new Set();
    document.querySelectorAll('.video-pod__list [data-key]').forEach(el => {
      const info = getBilibiliVideoInfo(el);
      if (!info || !info.link || seen.has(info.link)) return;
      seen.add(info.link);
      out.push({ title: info.title, link: info.link });
    });
    return out;
  }

  chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
    if (request.action === 'scrapeBilibiliCollection') {
      try {
        const videos = scrapeBilibiliVideoPodLists();
        sendResponse({ ok: true, videos });
      } catch (e) {
        sendResponse({ ok: false, error: e && e.message ? e.message : String(e) });
      }
    }
    return undefined;
  });

  // 等待DOM加载完成
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
