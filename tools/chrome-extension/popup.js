// popup.js
const API_URL = 'http://localhost:8765';
const STORAGE_KEY = 'selectedVideos';

// 页面加载时
document.addEventListener('DOMContentLoaded', async () => {
  const statusDiv = document.getElementById('status');
  const selectedCountDiv = document.getElementById('selectedCount');
  const countSpan = document.getElementById('count');
  const videoListDiv = document.getElementById('videoList');
  const batchActionsDiv = document.getElementById('batchActions');
  const addAllBtn = document.getElementById('addAllBtn');
  const clearAllBtn = document.getElementById('clearAllBtn');
  const autoNameCheckbox = document.getElementById('autoNameCheckbox');
  const loadingDiv = document.getElementById('loading');
  const messageDiv = document.getElementById('message');

  // 加载已选择的视频
  await loadSelectedVideos();

  // 监听storage变化（当content script修改选择时）
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === 'local' && changes[STORAGE_KEY]) {
      loadSelectedVideos();
    }
  });

  // 批量添加按钮
  addAllBtn.addEventListener('click', async () => {
    await addAllVideos();
  });

  // 清空所有选择
  clearAllBtn.addEventListener('click', async () => {
    if (confirm('确定要清空所有已选择的视频吗？')) {
      await chrome.storage.local.remove([STORAGE_KEY]);
      await loadSelectedVideos();
      showMessage('success', '已清空所有选择');
    }
  });

  // 加载已选择的视频
  async function loadSelectedVideos() {
    try {
      const result = await chrome.storage.local.get([STORAGE_KEY]);
      const selectedVideos = result[STORAGE_KEY] || [];

      if (selectedVideos.length === 0) {
        statusDiv.className = 'status empty';
        statusDiv.textContent = '📝 还没有选择任何视频\n在视频列表页面点击视频上的 ✓ 按钮来选择视频';
        selectedCountDiv.style.display = 'none';
        videoListDiv.style.display = 'none';
        batchActionsDiv.style.display = 'none';
        return;
      }

      statusDiv.className = 'status info';
      statusDiv.textContent = `✅ 已选择 ${selectedVideos.length} 个视频`;
      selectedCountDiv.style.display = 'block';
      countSpan.textContent = selectedVideos.length;
      videoListDiv.style.display = 'block';
      batchActionsDiv.style.display = 'block';

      // 渲染视频列表
      renderVideoList(selectedVideos);
    } catch (error) {
      console.error('Error loading selected videos:', error);
      showMessage('error', `加载失败: ${error.message}`);
    }
  }

  // 渲染视频列表
  function renderVideoList(videos) {
    videoListDiv.innerHTML = '';

    videos.forEach((video, index) => {
      const item = document.createElement('div');
      item.className = 'video-item';
      item.dataset.index = index;

      const defaultName = generateDefaultName(video.title, index);
      
      item.innerHTML = `
        <div class="title">${escapeHtml(video.title)}</div>
        <div class="url">${escapeHtml(video.link)}</div>
        <input type="text" class="name-input" value="${escapeHtml(defaultName)}" 
               placeholder="视频名称（用于生成文件名）" data-link="${escapeHtml(video.link)}">
        <button class="remove-btn" data-link="${escapeHtml(video.link)}" title="取消选择">×</button>
      `;

      // 移除按钮事件
      const removeBtn = item.querySelector('.remove-btn');
      removeBtn.addEventListener('click', async () => {
        await removeVideo(video.link);
      });

      videoListDiv.appendChild(item);
    });
  }

  // 移除单个视频
  async function removeVideo(link) {
    try {
      const result = await chrome.storage.local.get([STORAGE_KEY]);
      const selectedVideos = result[STORAGE_KEY] || [];
      const filtered = selectedVideos.filter(v => v.link !== link);
      await chrome.storage.local.set({ [STORAGE_KEY]: filtered });
      await loadSelectedVideos();
      showMessage('success', '已取消选择');
    } catch (error) {
      console.error('Error removing video:', error);
      showMessage('error', `移除失败: ${error.message}`);
    }
  }

  // 批量添加所有视频
  async function addAllVideos() {
    try {
      const result = await chrome.storage.local.get([STORAGE_KEY]);
      const selectedVideos = result[STORAGE_KEY] || [];

      if (selectedVideos.length === 0) {
        showMessage('error', '没有可添加的视频');
        return;
      }

      showLoading(true);
      showMessage('', '');

      const useAutoName = autoNameCheckbox.checked;
      let successCount = 0;
      let failCount = 0;
      const errors = [];

      // 逐个添加视频
      for (let i = 0; i < selectedVideos.length; i++) {
        const video = selectedVideos[i];
        
        // 获取用户输入的名称或自动生成
        let name;
        if (useAutoName) {
          name = generateDefaultName(video.title, i);
        } else {
          const nameInput = document.querySelector(`.name-input[data-link="${escapeHtml(video.link)}"]`);
          name = nameInput ? nameInput.value.trim() : generateDefaultName(video.title, i);
        }

        if (!name) {
          name = generateDefaultName(video.title, i);
        }

        try {
          // 生成shottitle（title的前20个字符）
          const shottitle = video.title ? video.title.substring(0, 20) : '';
          
          const response = await fetch(`${API_URL}/add-video`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
              name, 
              link: video.link,
              title: video.title || '',
              shottitle: shottitle
            }),
          });

          if (!response.ok) {
            const errorText = await response.text();
            let errorMsg = errorText || '添加失败';
            // 尝试解析错误信息
            try {
              const errorData = JSON.parse(errorText);
              errorMsg = errorData.error || errorMsg;
            } catch (e) {
              // 不是JSON格式，使用原始文本
            }
            throw new Error(errorMsg);
          }

          // 检查响应数据
          const data = await response.json();
          if (data.success) {
            successCount++;
          } else {
            throw new Error(data.error || '添加失败');
          }
        } catch (error) {
          failCount++;
          // 更详细地记录错误信息
          const errorMsg = error.message || String(error);
          errors.push({
            title: video.title,
            error: errorMsg,
            isNetworkError: errorMsg.includes('fetch') || errorMsg.includes('Failed to fetch') || errorMsg.includes('NetworkError')
          });
          console.error(`Error adding video ${video.title}:`, error);
        }
      }

      // 显示结果
      if (failCount === 0) {
        showMessage('success', `✅ 成功添加 ${successCount} 个视频到 videos.json`);
        // 清空选择
        await chrome.storage.local.remove([STORAGE_KEY]);
        await loadSelectedVideos();
      } else if (successCount > 0) {
        // 部分成功
        const networkErrors = errors.filter(e => e.isNetworkError);
        if (networkErrors.length > 0) {
          showMessage('error', `部分成功：${successCount} 个已添加，${failCount} 个失败（无法连接服务器）`);
        } else {
          showMessage('error', `部分成功：${successCount} 个已添加，${failCount} 个失败`);
        }
        if (errors.length > 0) {
          console.error('Errors:', errors);
        }
        // 即使部分失败，也清空选择（因为成功的已经添加了）
        await chrome.storage.local.remove([STORAGE_KEY]);
        await loadSelectedVideos();
      } else {
        // 全部失败
        const hasNetworkError = errors.some(e => e.isNetworkError);
        if (hasNetworkError) {
          showMessage('error', '无法连接到本地服务器。请确保已运行 server.py');
          // 显示复制JSON的选项
          showCopyJsonOption(selectedVideos);
        } else {
          const firstError = errors[0]?.error || '未知错误';
          showMessage('error', `添加失败：${firstError}`);
        }
      }
    } catch (error) {
      console.error('Error adding all videos:', error);
      showMessage('error', `批量添加失败: ${error.message}`);
    } finally {
      showLoading(false);
    }
  }

  // 显示复制JSON选项
  function showCopyJsonOption(videos) {
    const nameInputs = document.querySelectorAll('.name-input');
    const jsonItems = [];

    videos.forEach((video, index) => {
      const nameInput = Array.from(nameInputs).find(
        input => input.dataset.link === video.link
      );
      const name = nameInput ? nameInput.value.trim() : generateDefaultName(video.title, index);
      const shottitle = video.title ? video.title.substring(0, 20) : '';
      jsonItems.push({ 
        name, 
        link: video.link,
        title: video.title || '',
        shottitle: shottitle
      });
    });

    const jsonText = JSON.stringify(jsonItems, null, 2);
    
    // 创建复制按钮
    if (!document.getElementById('copyJsonBtn')) {
      const copyBtn = document.createElement('button');
      copyBtn.id = 'copyJsonBtn';
      copyBtn.className = 'btn btn-secondary';
      copyBtn.textContent = '复制 JSON 到剪贴板';
      copyBtn.style.marginTop = '8px';
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(jsonText).then(() => {
          showMessage('success', 'JSON 已复制到剪贴板！请手动添加到 videos.json');
        });
      });
      batchActionsDiv.appendChild(copyBtn);
    }
  }

  // 生成默认名称
  function generateDefaultName(title, index = 0) {
    // 从标题生成默认名称：去除特殊字符，限制长度
    let name = title
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .toLowerCase()
      .substring(0, 40);
    
    if (!name) {
      name = `video-${index + 1}`;
    }
    
    // 添加时间戳避免重复
    const timestamp = Date.now().toString().slice(-6);
    return `${name}-${timestamp}`;
  }

  // 显示消息
  function showMessage(type, text) {
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = text;
    if (type) {
      setTimeout(() => {
        messageDiv.className = 'message';
        messageDiv.textContent = '';
      }, 5000);
    }
  }

  // 显示加载状态
  function showLoading(show) {
    loadingDiv.className = show ? 'loading active' : 'loading';
    addAllBtn.disabled = show;
  }

  // HTML转义
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
});
