// background.js - Service Worker
// 用于处理后台任务和消息传递

chrome.runtime.onInstalled.addListener(() => {
  console.log('视频转文字稿助手已安装');
});

// 监听来自 content script 或 popup 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'selectionChanged') {
    // 选择状态改变时，可以在这里做一些处理
    console.log('视频选择状态已更新');
    sendResponse({ success: true });
  }
  return true;
});
