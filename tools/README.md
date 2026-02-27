# 视频转文字稿工具集

这个文件夹包含了用于批量处理视频转文字稿的辅助工具。

## 📁 目录结构

```
tools/
├── chrome-extension/     # Chrome 浏览器插件
│   ├── manifest.json    # 插件配置文件
│   ├── popup.html       # 插件弹窗界面
│   ├── popup.js         # 插件主要逻辑
│   ├── content.js       # 内容脚本
│   ├── background.js    # 后台服务
│   ├── icons/           # 插件图标
│   └── README.md        # 插件使用说明
└── server.py            # 本地服务器（用于插件写入 videos.json）
```

## 🚀 快速开始

### 1. 安装 Chrome 插件

1. 打开 Chrome 浏览器，访问 `chrome://extensions/`
2. 开启"开发者模式"
3. 点击"加载已解压的扩展程序"
4. 选择 `tools/chrome-extension` 文件夹

**注意**: 如果缺少图标文件，请先创建 `icons` 文件夹并添加图标（见 `chrome-extension/icons/README.md`）

### 2. 启动本地服务器（可选但推荐）

```bash
cd tools
python server.py
```

服务器会在 `http://localhost:8765` 启动，用于接收插件请求并直接写入 `videos.json`。

### 3. 使用流程

1. **选择视频**: 
   - 访问 B 站或 YouTube 视频页面
   - 点击浏览器工具栏中的插件图标
   - 插件会自动提取视频标题和链接

2. **添加视频**:
   - 编辑视频名称（用于生成文件名，如 `zz-video4`）
   - 点击"添加到 videos.json"（需要服务器运行）
   - 或点击"复制 JSON 到剪贴板"，手动添加到 `videos.json`

3. **批量处理**:
   ```bash
   python batch_whisperx.py
   ```
   脚本会自动读取 `videos.json`，下载所有视频的音频，转写为文字稿，并使用 AI 整理。

## 📝 工作流程

```
Chrome 插件选择视频
    ↓
添加到 videos.json
    ↓
运行 batch_whisperx.py
    ↓
自动下载音频 → WhisperX 转写 → AI 整理 → 生成摘要
    ↓
输出到 output/ 目录
```

## 🔧 配置说明

### Chrome 插件

- 支持网站: B 站 (bilibili.com) 和 YouTube
- API 地址: `http://localhost:8765`（可在 `popup.js` 中修改）

### 本地服务器

- 端口: 8765（可在 `server.py` 中修改）
- 配置文件: 项目根目录的 `videos.json`

## ❓ 常见问题

**Q: 插件无法连接到服务器？**

A: 确保已运行 `python tools/server.py`，并且端口 8765 未被占用。

**Q: 不想运行服务器怎么办？**

A: 可以使用"复制 JSON 到剪贴板"功能，然后手动将内容添加到 `videos.json`。

**Q: 插件图标显示异常？**

A: 请确保 `icons` 文件夹中有三个图标文件（16x16, 48x48, 128x128）。

## 📚 更多信息

- Chrome 插件详细说明: [chrome-extension/README.md](chrome-extension/README.md)
- 主程序说明: 项目根目录的 `batch_whisperx.py`

