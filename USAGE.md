# Usage

## `app/main.py`（Web 实时转写）

```powershell
.venv\Scripts\Activate.ps1
python -m app.main
```

浏览器打开：`http://127.0.0.1:5444`（端口见 `app/config.py`）

### Chrome 多页签分别听写

本机麦克风转写只能听到「混音」；若要 **N 个页签各出一份字**，请加载扩展：

1. 先按上面命令启动 `python -m app.main`
2. Chrome → `chrome://extensions` → 开发者模式 → 加载已解压的扩展程序  
   目录：`tools/chrome-tab-transcribe`
3. 勾选多个正在播放的页签 →「开始监听所选」（可用「打开大面板」看分路文字）

详见 `tools/chrome-tab-transcribe/README.md`。后端接口：`/ws/tab`（每页签一条 WebSocket，收 16kHz float32 PCM）。

### Chrome 评论角度助手

按贴文上下文生成多条候选评论并择一使用（可配 API Key、自定义角色角度）：

1. `chrome://extensions` → 加载已解压扩展：`tools/chrome-comment-assistant`
2. 设置里填 API Key（默认通义 OpenAI 兼容模式）
3. 打开帖子页 → 生成 → 选择一条 → 复制或填入评论框

详见 `tools/chrome-comment-assistant/README.md`。

---

## `batch_whisperx_nodownload.py`（流式转写，不落盘音频）

**按 `videos.json` 批量：**

```powershell
python batch_whisperx_nodownload.py --mode file

# 使用多线程
export OMP_NUM_THREADS=8 测试多线程会不会快
python batch_whisperx_nodownload.py
```

**命令行 URL 模式（只要出现 `--url` 即不读 `videos.json`，默认 `--mode file` 可不写）：**

```powershell
python batch_whisperx_nodownload.py --url "https://..."
python batch_whisperx_nodownload.py --url URL1 --url URL2 --name a --name b
```

**实时 WebSocket 队列（默认 `127.0.0.1:3333`）：**

```powershell
python batch_whisperx_nodownload.py --mode realtime
```

**YouTube 提示 “Sign in / bot” 时：** 在已登录 YouTube 的浏览器里导出 Netscape 格式 `cookies.txt`。脚本会按顺序使用：`YOUTUBE_COOKIES_FILE` → 项目根 `youtube_cookies.txt` → `D:\frontend\main\tools\youtube_cookies.txt`。也可设 `YOUTUBE_COOKIES_FROM_BROWSER=chrome`。

---

## `download_m3u8.py`（m3u8 下载合并）

**命令行指定 m3u8：**

```powershell
python download_m3u8.py -u "https://example.com/playlist.m3u8" -o out.ts
python download_m3u8.py -u URL1 -u URL2
```

**脚本内 `DOWNLOAD_LIST` 批量（不传参数）：**

```powershell
python download_m3u8.py
```

依赖：`pip install pycryptodome`；合并分片建议系统已安装 `ffmpeg`。
