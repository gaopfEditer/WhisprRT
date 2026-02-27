// content.js - 在视频列表页面注入选择按钮
(function() {
  'use strict';

  const SELECTOR_BUTTON_ID = 'whispr-select-btn';
  const STORAGE_KEY = 'selectedVideos';

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

  // 获取B站视频信息
  function getBilibiliVideoInfo(element) {
    try {
      // 根据B站实际HTML结构提取
      // 优先查找 .bili-cover-card 或 .bili-video-card__title 内的链接
      let linkElement = element.querySelector('.bili-cover-card');
      
      if (!linkElement) {
        linkElement = element.querySelector('.bili-video-card__title a');
      }
      
      // 如果没找到，尝试查找包含 /video/BV 或 /video/av 的链接
      if (!linkElement) {
        linkElement = element.querySelector('a[href*="/video/BV"], a[href*="/video/av"]');
      }

      // 如果还是没找到，在所有链接中查找
      if (!linkElement) {
        const allLinks = element.querySelectorAll('a');
        for (const link of allLinks) {
          const href = link.getAttribute('href') || '';
          if (href.includes('/video/BV') || href.includes('/video/av')) {
            linkElement = link;
            break;
          }
        }
      }

      if (!linkElement) {
        console.log('[B站调试] 未找到链接元素，元素内容:', element.outerHTML.substring(0, 200));
        return null;
      }

      let href = linkElement.getAttribute('href') || '';
      
      if (!href) {
        console.log('[B站调试] 链接元素的href为空');
        return null;
      }
      
      // 处理相对路径和绝对路径
      // B站链接可能是 //www.bilibili.com/... 或 /video/...
      if (href.startsWith('//')) {
        href = 'https:' + href;
      } else if (href.startsWith('/')) {
        href = 'https://www.bilibili.com' + href;
      } else if (!href.startsWith('http')) {
        href = 'https://www.bilibili.com/' + href;
      }

      // 提取视频ID（BV号或av号）
      const bvMatch = href.match(/\/video\/(BV[\w]+)/);
      const avMatch = href.match(/\/video\/(av\d+)/i);
      
      if (bvMatch || avMatch) {
        const videoId = bvMatch ? bvMatch[1] : avMatch[1];
        href = `https://www.bilibili.com/video/${videoId}`;
      } else {
        console.log('[B站调试] 无法从链接中提取视频ID:', href);
        return null;
      }

      // 移除查询参数和锚点
      const fullUrl = href.split('?')[0].split('#')[0];
      const title = extractBilibiliTitle(element, linkElement);

      if (!title || !title.trim()) {
        console.log('[B站调试] 无法提取标题');
      }

      return {
        title: title.trim() || '未知标题',
        link: fullUrl,
        element: element
      };
    } catch (e) {
      console.error('[B站调试] 提取视频信息时出错:', e, element);
      return null;
    }
  }

  // 提取B站标题
  function extractBilibiliTitle(element, linkElement) {
    // 根据B站实际HTML结构：.bili-video-card__title 有 title 属性
    // 这是最准确的方式，必须严格只从这个元素获取
    const titleElement = element.querySelector('.bili-video-card__title');
    if (titleElement) {
      // 优先使用 title 属性（这是B站标准方式，最准确）
      let title = titleElement.getAttribute('title');
      if (title && title.trim()) {
        return title.trim();
      }
      
      // 如果没有 title 属性，从内部 a 标签获取文本（只获取第一个a标签）
      const titleLink = titleElement.querySelector('a');
      if (titleLink) {
        title = titleLink.textContent || titleLink.innerText;
        if (title && title.trim()) {
          // 清理文本：移除换行、多余空格
          title = title.replace(/\s+/g, ' ').trim();
          // 过滤掉明显不是标题的内容（如播放量、时长等）
          if (!title.match(/^\d+[\.\d]*[万千]?\s*[\d:]+$/)) {
            return title;
          }
        }
      }
      
      // 如果a标签的文本也不对，尝试直接获取titleElement的文本
      // 但要排除包含"添加至"、"稍后再看"等按钮文本
      title = titleElement.textContent || titleElement.innerText;
      if (title && title.trim()) {
        // 清理文本：移除换行、多余空格
        title = title.replace(/\s+/g, ' ').trim();
        // 过滤掉明显不是标题的内容
        if (!title.includes('添加至') && 
            !title.includes('稍后再看') && 
            !title.match(/^\d+[\.\d]*[万千]?\s*[\d:]+$/)) {
          return title;
        }
      }
    }

    // 如果 .bili-video-card__title 不存在或提取失败，尝试其他方式
    // 但这是备用方案，应该很少用到
    if (linkElement && linkElement.classList.contains('bili-cover-card')) {
      // 如果链接元素是 .bili-cover-card，尝试从父容器查找标题
      const parentTitle = linkElement.closest('.bili-video-card__wrap')?.querySelector('.bili-video-card__title');
      if (parentTitle) {
        let title = parentTitle.getAttribute('title');
        if (title && title.trim()) {
          return title.trim();
        }
      }
    }

    // 最后备用：从链接元素的title属性获取（但通常链接元素没有title）
    if (linkElement) {
      let title = linkElement.getAttribute('title');
      if (title && title.trim() && 
          !title.includes('添加至') && 
          !title.includes('稍后再看')) {
        return title.trim();
      }
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

  // 为视频项添加选择按钮
  function addButtonsToVideos() {
    const url = window.location.href;
    let videoItems = [];

    if (url.includes('bilibili.com')) {
      // B站视频列表选择器（根据实际HTML结构）
      // 优先使用 .bili-video-card__wrap（这是B站视频卡片的标准容器）
      videoItems = document.querySelectorAll('.bili-video-card__wrap');
      
      console.log(`[B站调试] 找到 ${videoItems.length} 个 .bili-video-card__wrap 元素`);
      
      // 如果没找到，尝试其他选择器
      if (videoItems.length === 0) {
        videoItems = document.querySelectorAll(
          '.bili-video-card, ' +
          '[class*="bili-video-card__wrap"], ' +
          '[class*="bili-video-card"]'
        );
        console.log(`[B站调试] 使用备用选择器找到 ${videoItems.length} 个元素`);
      }

      // 如果还是没找到，使用更通用的方法：查找所有包含BV链接的元素
      if (videoItems.length === 0) {
        const allLinks = document.querySelectorAll('a[href*="/video/BV"], a[href*="/video/av"]');
        console.log(`[B站调试] 找到 ${allLinks.length} 个视频链接`);
        
        const uniqueContainers = new Set();
        allLinks.forEach(link => {
          // 向上查找 .bili-video-card__wrap 容器
          let container = link.closest('.bili-video-card__wrap');
          if (!container) {
            // 如果找不到，向上查找其他合适的容器
            container = link.closest('li, div[class*="card"], div[class*="item"], article, section');
          }
          if (!container) {
            // 如果还是找不到，使用父元素的父元素
            container = link.parentElement?.parentElement;
          }
          if (container && !container.querySelector(`.${SELECTOR_BUTTON_ID}`)) {
            uniqueContainers.add(container);
          }
        });
        videoItems = Array.from(uniqueContainers);
        console.log(`[B站调试] 通过链接查找找到 ${videoItems.length} 个容器`);
      }
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
          if (node.nodeType !== 1) return false; // 不是元素节点
          return node.matches && (
            node.matches('.bili-video-card__wrap') ||
            node.querySelector && node.querySelector('.bili-video-card__wrap')
          );
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

  // 等待DOM加载完成
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
