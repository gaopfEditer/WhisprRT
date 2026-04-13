# Usage

## `app/main.py`（Web 实时转写）

```powershell
.venv\Scripts\Activate.ps1
python -m app.main
```

浏览器打开：`http://127.0.0.1:5444`（端口见 `app/config.py`）

---

## `batch_whisperx_nodownload.py`（流式转写，不落盘音频）

**按 `videos.json` 批量：**

```powershell
python batch_whisperx_nodownload.py --mode file
```

**命令行指定链接（不读 `videos.json`）：**

```powershell
python batch_whisperx_nodownload.py --mode file --url "https://..."
python batch_whisperx_nodownload.py --mode file --url URL1 --url URL2 --name a --name b
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
