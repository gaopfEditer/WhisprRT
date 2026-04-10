"""
批量流式转写脚本 - 无需下载，直接获取 URL 音视频流并转写中文字稿

技术方案：yt-dlp 获取真实流地址 → FFmpeg 管道转 16k 单声道 PCM → faster-whisper 推理
配置文件：videos.json（与 batch_whisperx 共用）

依赖：yt-dlp, ffmpeg, faster-whisper, numpy, requests
  pip install yt-dlp faster-whisper numpy requests

若报错 cudnn_ops64_9.dll / cudnnCreateTensorDescriptor：说明缺 cuDNN 或未加入 PATH，
  可强制用 CPU 运行（较慢但无需 GPU）：运行前设置环境变量 USE_CPU=1
  PowerShell: $env:USE_CPU="1"; python batch_whisperx_nodownload.py

YouTube 若提示 Sign in / bot：Cookie 查找顺序为 YOUTUBE_COOKIES_FILE → 项目根 youtube_cookies.txt
  → D:\\frontend\\main\\tools\\youtube_cookies.txt；或设 YOUTUBE_COOKIES_FROM_BROWSER=chrome
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import traceback
from pathlib import Path

import numpy as np
import websockets


def get_ffmpeg_path() -> str:
    """解析 ffmpeg 可执行路径（PATH 或常见安装位置）。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise FileNotFoundError(
        "未找到 ffmpeg。请安装：macOS 用 brew install ffmpeg，Windows 从 https://ffmpeg.org 下载并加入 PATH"
    )


import requests
import yt_dlp
from faster_whisper import WhisperModel

# 配置文件路径（与 batch_whisperx 共用）
CONFIG_PATH = Path("videos.json")

# YouTube Cookie（Netscape 格式）：优先 YOUTUBE_COOKIES_FILE，其次项目根 youtube_cookies.txt，再其次本路径
YOUTUBE_COOKIES_FILE_DEFAULT = Path(r"D:\frontend\main\tools\youtube_cookies.txt")

# 输出目录
TRANSCRIPT_DIR = Path("subtitles")
LOG_DIR = Path("logs")
OUTPUT_DIR = Path("output")
REALTIME_HOST = "127.0.0.1"
REALTIME_PORT = 3333

# faster-whisper 参数
WHISPER_MODEL = "large-v3-turbo"
WHISPER_LANGUAGE = "zh"

def _detect_device():
    if os.environ.get("USE_CPU", "").strip().lower() in ("1", "true", "yes"):
        return "cpu"
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"

WHISPER_DEVICE = _detect_device()
# 默认用 int8 兼容更多 GPU（部分显卡不支持 float16）；需要 float16 可设环境变量 USE_FLOAT16=1
_use_float16 = os.environ.get("USE_FLOAT16", "").strip().lower() in ("1", "true", "yes")
WHISPER_COMPUTE_TYPE = "float16" if (WHISPER_DEVICE == "cuda" and _use_float16) else "int8"

# 通义千问配置（与 batch_whisperx 相同）
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "sk-40fc3963ae51439db02c07d7b9995042")
QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
QWEN_MODEL = "qwen-turbo"

# 全局模型实例（避免每次重复加载）
_whisper_model: WhisperModel | None = None


def get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        print(f"\n>>> 加载 Whisper 模型: {WHISPER_MODEL} ({WHISPER_DEVICE}, {WHISPER_COMPUTE_TYPE})")
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _whisper_model


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _is_youtube_link(link: str) -> bool:
    low = link.lower()
    return "youtube.com" in low or "youtu.be" in low or "m.youtube.com" in low


def _youtube_cookie_hint() -> str:
    return (
        "YouTube 要求验证身份时，请导出浏览器 Cookie 为 Netscape 格式：\n"
        "  1) 安装扩展「Get cookies.txt LOCALLY」等，在已登录 YouTube 的浏览器里导出；\n"
        "  2) 保存为项目目录下的 youtube_cookies.txt，或 D:\\frontend\\main\\tools\\youtube_cookies.txt，或设置 YOUTUBE_COOKIES_FILE；\n"
        "  3) 或设置 YOUTUBE_COOKIES_FROM_BROWSER=chrome（或 edge、firefox 等，需本机已登录）；\n"
        "详见：https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp\n"
    )


def _is_storyboard_or_nonmedia_url(f: dict, url: str) -> bool:
    """
    YouTube 等站会把「预览图 / storyboard」放进 formats，带 url 但无音视频流。
    若误选会导致 FFmpeg 去拉 i.ytimg.com/sb/...jpg，报 404 或 I/O 错误。
    """
    if not url:
        return True
    low = url.lower()
    if "i.ytimg.com/sb/" in low or "/storyboard" in low:
        return True
    if "ytimg.com" in low and "/sb/" in low:
        return True
    fid = str(f.get("format_id") or "")
    if re.match(r"^sb\d*$", fid, re.I):
        return True
    fn = (f.get("format_note") or "") + " " + (f.get("resolution") or "")
    if "storyboard" in fn.lower():
        return True
    ac = f.get("acodec")
    vc = f.get("vcodec")
    if ac in (None, "none") and vc in (None, "none"):
        if low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return True
        if "ytimg.com" in low:
            return True
    return False


def _url_looks_like_http_media_stream(url: str) -> bool:
    """无 acodec 的条目仅当 URL 明显是 CDN 上的媒体流时才可作兜底（避免 storyboard）。"""
    low = url.lower()
    if "i.ytimg.com/sb/" in low or "/storyboard" in low:
        return False
    if "googlevideo.com" in low:
        return True
    if ".m3u8" in low or "/manifest/" in low:
        return True
    if "videoplayback" in low and ("googlevideo" in low or "googleusercontent" in low):
        return True
    if re.search(r"\.(mp4|webm|m4a|mp3|ts|mkv|mov)(\?|$|#)", low):
        return True
    return False


def _pick_stream_url_from_formats_dict(info: dict) -> tuple[str, float | None] | None:
    """
    从 extract_info(..., process=False) 返回的 info['formats'] 里挑一条可直接给 FFmpeg 的 URL。
    不经过 yt-dlp 的 format 字符串，避免「Requested format is not available」。
    """
    fmts = info.get("formats")
    if not fmts:
        return None
    try:
        rows = list(fmts)
    except Exception:
        return None

    dur = info.get("duration")
    if dur is not None:
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = None

    audio_only: list[tuple[float, str]] = []
    muxed: list[tuple[float, str]] = []
    fallback_urls: list[str] = []

    for f in rows:
        u = f.get("url")
        if not u:
            continue
        if _is_storyboard_or_nonmedia_url(f, u):
            continue
        ac = f.get("acodec")
        vc = f.get("vcodec")
        if ac in (None, "none"):
            if _url_looks_like_http_media_stream(u):
                fallback_urls.append(u)
            continue
        if vc in (None, "none"):
            abr = f.get("abr") or 0
            try:
                abr = float(abr)
            except (TypeError, ValueError):
                abr = 0.0
            audio_only.append((abr, u))
        else:
            tbr = f.get("tbr") or f.get("abr") or 0
            try:
                tbr = float(tbr)
            except (TypeError, ValueError):
                tbr = 0.0
            muxed.append((tbr, u))

    if audio_only:
        audio_only.sort(key=lambda x: x[0], reverse=True)
        return (audio_only[0][1], dur)
    if muxed:
        muxed.sort(key=lambda x: x[0], reverse=True)
        return (muxed[0][1], dur)
    if fallback_urls:
        return (fallback_urls[0], dur)
    return None


def _is_retryable_format_error(e: BaseException) -> bool:
    err_low = str(e).lower()
    if "requested format is not available" in err_low:
        return True
    if "format is not available" in err_low:
        return True
    if "no video formats" in err_low or "no audio formats" in err_low:
        return True
    if "unable to download" in err_low and "format" in err_low:
        return True
    return False


def _ydl_extract_stream_url(link: str, ydl_opts: dict) -> tuple[str, float | None]:
    """
    优先：extract_info(..., process=False) 跳过 format 选择器，从 formats 里手动挑 URL。
    否则再尝试多种 format 字符串（兼容旧逻辑）。
    """
    opts_no_fmt = {k: v for k, v in ydl_opts.items() if k != "format"}
    last_err: Exception | None = None

    try:
        with yt_dlp.YoutubeDL(opts_no_fmt) as ydl:
            info = ydl.extract_info(link, download=False, process=False)
        if info:
            picked = _pick_stream_url_from_formats_dict(info)
            if picked:
                return picked
    except Exception as e:
        err_s = str(e)
        err_low = err_s.lower()
        if _is_youtube_link(link) and (
            "sign in" in err_low or "bot" in err_low or "cookies" in err_low
        ):
            raise
        last_err = e
        if not _is_retryable_format_error(e) and "not available" not in err_low:
            raise

    format_chain = (
        ydl_opts.get("format") or "bestaudio/bestaudio*/best/b/worst",
        "ba/b",
        "bestvideo+bestaudio/best/ba/b/worst",
        "bv*+ba/b",
        "best/worst",
        "worst",
    )
    seen: set[str] = set()
    for fmt in format_chain:
        if not fmt or fmt in seen:
            continue
        seen.add(fmt)
        opts = {**ydl_opts, "format": fmt}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
            return _extract_url_duration_from_info(info, link)
        except Exception as e:
            last_err = e
            if _is_retryable_format_error(e):
                continue
            raise

    try:
        with yt_dlp.YoutubeDL(opts_no_fmt) as ydl:
            info = ydl.extract_info(link, download=False)
        return _extract_url_duration_from_info(info, link)
    except Exception as e2:
        last_err = e2

    if last_err:
        raise last_err
    raise RuntimeError("yt-dlp 无法解析可用流格式")


def _merge_youtube_ydl_opts(base: dict) -> dict:
    """为 YouTube 合并 cookiefile、cookiesfrombrowser，并设置 player_client 以拿到更多格式。"""
    opts = {**base}
    cookie_file = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if not cookie_file:
        default_cookie = CONFIG_PATH.parent / "youtube_cookies.txt"
        if default_cookie.is_file():
            cookie_file = str(default_cookie)
    if not cookie_file and YOUTUBE_COOKIES_FILE_DEFAULT.is_file():
        cookie_file = str(YOUTUBE_COOKIES_FILE_DEFAULT)
    if cookie_file and os.path.isfile(cookie_file):
        opts["cookiefile"] = cookie_file
    else:
        browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
        if browser:
            parts = browser.split(":", 1)
            name = parts[0].strip()
            if len(parts) > 1 and parts[1].strip():
                opts["cookiesfrombrowser"] = (name, parts[1].strip())
            else:
                opts["cookiesfrombrowser"] = (name,)

    # 换客户端解析，减少「无可用格式」（与 Cookie 分支无关，统一追加）
    ex = dict(opts.get("extractor_args") or {})
    yt = dict(ex.get("youtube") or {})
    if not yt.get("player_client"):
        yt["player_client"] = ["android", "web", "ios"]
    ex["youtube"] = yt
    opts["extractor_args"] = ex
    return opts


def _extract_url_duration_from_info(info: dict | None, link: str) -> tuple[str, float | None]:
    if info is None:
        raise RuntimeError(f"无法获取视频信息: {link}")
    url = info.get("url")
    # bestvideo+bestaudio 等：顶层无 url，在 requested_formats 里
    if not url and info.get("requested_formats"):
        for rf in info["requested_formats"]:
            u = rf.get("url")
            if not u:
                continue
            # 优先只要音轨（给 FFmpeg 抽音频更省事）
            if rf.get("acodec") not in (None, "none") and rf.get("vcodec") in ("none", None):
                url = u
                break
        if not url:
            for rf in info["requested_formats"]:
                u = rf.get("url")
                if u and rf.get("acodec") not in (None, "none"):
                    url = u
                    break
        if not url:
            for rf in info["requested_formats"]:
                if rf.get("url"):
                    url = rf["url"]
                    break
    if not url:
        formats = info.get("formats") or []
        for f in formats:
            u = f.get("url")
            if u and (f.get("vcodec") == "none" or f.get("acodec") != "none"):
                url = u
                break
        if not url and formats:
            url = next((f.get("url") for f in formats if f.get("url")), None)
    if not url:
        raise RuntimeError(f"无法获取流地址: {link}")
    duration = info.get("duration")
    return (url, float(duration) if duration is not None else None)


def get_stream_url(link: str) -> tuple[str, float | None]:
    """使用 yt-dlp 获取音视频流的真实 URL 与时长（秒），不下载。返回 (url, duration_sec)，duration 可能为 None。"""
    ydl_opts = {
        # 默认优先纯音频；若无匹配，由 _ydl_extract_stream_url 回退到含视频的 best
        "format": "bestaudio/bestaudio*/best/b/worst",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    douyin_cookie_hint = (
        "抖音仅支持 Cookie 文件。请用 Chrome 扩展「Get cookies.txt LOCALLY」或「cookies.txt」"
        "在打开该抖音链接后导出，保存为项目目录下的 batch_deal_dy_cookie.txt（或设置 DOUYIN_COOKIES_FILE）。"
        "若仍报 Fresh cookies，请：1) 在 Chrome 打开该链接并播放/刷新；2) 不关页面，立即用扩展导出；3) 覆盖 batch_deal_dy_cookie.txt 后重试。"
        "也可尝试升级 yt-dlp：uv pip install -U yt-dlp"
    )
    if "douyin" in link.lower():
        cookie_file = os.environ.get("DOUYIN_COOKIES_FILE", "").strip()
        if not cookie_file:
            default_cookie = CONFIG_PATH.parent / "batch_deal_dy_cookie.txt"
            if default_cookie.is_file():
                cookie_file = str(default_cookie)
        if not cookie_file or not os.path.isfile(cookie_file):
            raise RuntimeError(
                f"未找到抖音 Cookie 文件。请将 cookies.txt 保存为 batch_deal_dy_cookie.txt 放到项目目录，或设置 DOUYIN_COOKIES_FILE。\n{douyin_cookie_hint}"
            )
        # 设备模拟 + Cookie 文件，提高抖音解析成功率
        opts = {
            **ydl_opts,
            "cookiefile": cookie_file,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "extractor_args": {"douyin": ["device_id=73000000000", "iid=1234567890"]},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
                if info is None:
                    raise RuntimeError("无法获取视频信息")
                url = info.get("url")
                if not url:
                    formats = info.get("formats") or []
                    for f in formats:
                        u = f.get("url")
                        if u and (f.get("vcodec") == "none" or f.get("acodec") != "none"):
                            url = u
                            break
                    if not url and formats:
                        url = next((f.get("url") for f in formats if f.get("url")), None)
                if url:
                    duration = info.get("duration")
                    return (url, float(duration) if duration is not None else None)
        except Exception as e:
            raise RuntimeError(f"{douyin_cookie_hint}\n原始错误: {e}") from e

    if _is_youtube_link(link):
        ydl_opts = _merge_youtube_ydl_opts(ydl_opts)
    try:
        return _ydl_extract_stream_url(link, ydl_opts)
    except Exception as e:
        err = str(e)
        if _is_youtube_link(link) and (
            "Sign in" in err or "bot" in err.lower() or "cookies" in err.lower()
        ):
            raise RuntimeError(f"{_youtube_cookie_hint()}\n原始错误: {e}") from e
        raise


def stream_to_audio_array(stream_url: str, duration_sec: float | None = None) -> np.ndarray:
    """
    使用 FFmpeg 将流转为 16kHz 单声道 float32 数组（Whisper 所需格式）。
    若提供 duration_sec，会按读取字节数估算并打印转码进度。
    """
    cmd = [
        get_ffmpeg_path(),
        "-hide_banner", "-loglevel", "error",
    ]
    if "bilibili" in stream_url or "bilivideo" in stream_url:
        cmd.extend([
            "-headers",
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\nReferer: https://www.bilibili.com/\r\n",
        ])
    cmd.extend([
        "-i", stream_url,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-",
    ])
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # 已知时长时按字节估算进度：16kHz * 2 字节 = 32000 字节/秒
    chunk_size = 256 * 1024
    expected_bytes = int(duration_sec * 32000) if duration_sec and duration_sec > 0 else None
    raw_chunks = []
    bytes_read = 0
    last_pct = -1

    if process.stdout:
        while True:
            chunk = process.stdout.read(chunk_size)
            if not chunk:
                break
            raw_chunks.append(chunk)
            bytes_read += len(chunk)
            if expected_bytes and expected_bytes > 0:
                pct = min(100, int(bytes_read / expected_bytes * 100))
                if pct >= last_pct + 5 or pct == 100:
                    print(f"\r    FFmpeg 转码: {pct}%", end="", flush=True)
                    last_pct = pct
    raw_bytes = b"".join(raw_chunks)
    stderr = process.stderr.read() if process.stderr else b""
    process.wait()
    if last_pct >= 0:
        print()
    if process.returncode != 0:
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        raise RuntimeError(f"FFmpeg 转码失败 (code={process.returncode}): {err}")

    if len(raw_bytes) == 0:
        raise RuntimeError("FFmpeg 未输出任何数据，可能流地址无效或视频无音轨")

    # int16 -> float32, 范围 [-1, 1]
    audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def transcribe_audio_array(
    audio: np.ndarray,
    progress_callback=None,
) -> list[tuple[float, float, str]]:
    """使用 faster-whisper 转写，返回 [(start, end, text), ...]。可选 progress_callback(end_sec, total_sec, n_segments) 用于进度。"""
    model = get_whisper_model()
    total_sec = len(audio) / 16000.0
    segments_gen, _ = model.transcribe(
        audio,
        language=WHISPER_LANGUAGE,
        beam_size=1,
        vad_filter=True,
    )
    result = []
    last_pct = -1
    for seg in segments_gen:
        result.append((seg.start, seg.end, (seg.text or "").strip()))
        if progress_callback:
            progress_callback(seg.end, total_sec, len(result))
        elif total_sec > 0:
            pct = min(100, int(seg.end / total_sec * 100))
            if pct >= last_pct + 5 or pct == 100:
                print(f"\r    转写进度: {pct}% ({len(result)} 段)", end="", flush=True)
                last_pct = pct
    if last_pct >= 0:
        print()
    return result


def stream_transcribe(name: str, link: str) -> Path:
    """
    不下载，直接流转写：获取流 URL → FFmpeg 转 PCM → faster-whisper 转写
    输出到 subtitles/name.txt 和 logs/name.txt
    """
    ensure_dirs()
    transcript_path = TRANSCRIPT_DIR / f"{name}.txt"
    log_path = LOG_DIR / f"{name}.txt"

    print(f"\n>>> 获取流地址: {link}")
    stream_url, duration_sec = get_stream_url(link)
    if duration_sec is not None:
        print(f"    视频时长约 {duration_sec:.0f} 秒")

    print(f">>> FFmpeg 转码中（16k 单声道）...")
    audio = stream_to_audio_array(stream_url, duration_sec)
    duration_sec = len(audio) / 16000
    print(f"    音频时长约 {duration_sec:.1f} 秒")

    print(f">>> 转写中 -> {transcript_path}")
    segments = transcribe_audio_array(audio)

    # 生成与 WhisperX 类似的输出格式，便于后续 Qwen 处理
    lines = []
    plain_parts = []
    for start, end, text in segments:
        if not text:
            continue
        line = f"[{start:.2f}s -> {end:.2f}s] {text}"
        lines.append(line)
        plain_parts.append(text)

    raw_output = "\n".join(lines)
    transcript_path.write_text(raw_output, encoding="utf-8")
    log_path.write_text(raw_output, encoding="utf-8")

    print(f"✅ 转写完成: {transcript_path}")
    return transcript_path


def extract_plain_text_from_transcript(raw_text: str) -> str:
    """
    从转写输出提取纯文本。
    支持两种格式：
    1) [start -> end] text
    2) Transcript: [time] text (WhisperX 格式，兼容)
    """
    lines = raw_text.splitlines()
    texts = []
    # [0.00s -> 2.50s] 中文内容
    pattern1 = re.compile(r"^\[\d+(?:\.\d+)?s\s*->\s*\d+(?:\.\d+)?s\]\s*(.*)$")
    # Transcript: [time] 中文内容
    pattern2 = re.compile(r"^Transcript:\s*\[[^\]]+\]\s*(.*)$")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = pattern1.match(line) or pattern2.match(line)
        if m:
            content = m.group(1).strip()
            if content:
                texts.append(content)
        elif not line.startswith(("UserWarning", "INFO", "WARNING", "Downloading")):
            texts.append(line)

    return " ".join(texts)


def call_qwen(prompt: str) -> str:
    """调用通义千问 API"""
    if not QWEN_API_KEY:
        raise RuntimeError("QWEN_API_KEY 未配置")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }
    payload = {
        "model": QWEN_MODEL,
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"temperature": 0.7, "max_tokens": 2000},
    }
    resp = requests.post(QWEN_ENDPOINT, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Qwen API 调用失败 ({resp.status_code}): {resp.text}")

    data = resp.json()
    if "output" in data and "choices" in data["output"]:
        if data["output"]["choices"]:
            return data["output"]["choices"][0]["message"]["content"]
    if "output" in data and "text" in data["output"]:
        return data["output"]["text"]
    raise RuntimeError(f"Qwen 返回格式异常: {data}")


def refine_transcript_with_qwen(name: str, transcript_path: Path) -> Path:
    """AI 断句整理 + 摘要，保存到 output/name.txt"""
    raw = transcript_path.read_text(encoding="utf-8")
    plain_text = extract_plain_text_from_transcript(raw)
    if not plain_text.strip():
        raise RuntimeError("未提取到有效文本")

    system_prompt = (
        "你是一个中文文字编辑助手。"
        "现在给你一段由语音识别得到的中文文本，内容已经基本正确，但存在："
        "1）断句混乱；2）简繁体混用；3）口语化、重复、无意义语气词。\n\n"
        "请你：\n"
        "- 合并所有片段，按语义正确断句成自然的中文段落；\n"
        "- 统一为简体中文；\n"
        "- 保留原视频的含义，不要自行编造新内容；\n"
        "- 删除明显重复的句子和无意义的口头语；\n"
        "- 输出纯文本，不要加标题、前言或总结。\n\n"
        "下面是待整理的原始转写文本：\n"
    )
    refined_text = call_qwen(system_prompt + plain_text).strip()

    summary_prompt = (
        "你是一个内容摘要助手。"
        "请为以下文本生成一个简洁准确的摘要，控制在100-200字以内。"
        "摘要应该概括文本的核心内容和主要观点。\n\n"
        "待摘要的文本：\n"
    )
    summary = call_qwen(summary_prompt + refined_text).strip()

    final_output = f"摘要：{summary}\n\n全文：{refined_text}"
    ensure_dirs()
    refined_path = OUTPUT_DIR / f"{name}.txt"
    refined_path.write_text(final_output, encoding="utf-8")
    return refined_path


def process_item_once(item: dict) -> dict:
    """处理单个任务（一次尝试），返回包含文字稿的结果。"""
    name = item.get("name")
    link = item.get("link")
    if not name or not link:
        raise ValueError(f"任务缺少 name/link 字段: {item}")

    transcript_path = stream_transcribe(name, link)
    raw_text = transcript_path.read_text(encoding="utf-8")
    plain_text = extract_plain_text_from_transcript(raw_text)

    refined_text = None
    refined_path = None
    try:
        refined_path_obj = refine_transcript_with_qwen(name, transcript_path)
        refined_path = str(refined_path_obj)
        refined_text = refined_path_obj.read_text(encoding="utf-8")
    except Exception as e:
        # AI 精排失败不影响主流程
        print(f"⚠ AI 处理失败（跳过）：{e}")

    result = {
        **item,
        "status": "success",
        "transcript": plain_text,
        "raw_transcript": raw_text,
        "refined_text": refined_text,
        "transcript_path": str(transcript_path),
        "refined_path": refined_path,
    }
    return result


def process_item_with_retry(item: dict, retries: int = 3) -> dict:
    """处理单个任务，失败最多重试 retries 次（总次数=1+retries）。"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            print(f"\n>>> 处理任务 {item.get('name')}，第 {attempt + 1}/{retries + 1} 次")
            return {
                **process_item_once(item),
                "attempt": attempt + 1,
                "max_attempts": retries + 1,
            }
        except Exception as e:
            last_error = e
            print(f"[ERROR] 任务失败，第 {attempt + 1}/{retries + 1} 次: {e}")
            traceback.print_exc()
    return {
        **item,
        "status": "error",
        "error": str(last_error) if last_error else "unknown error",
        "attempt": retries + 1,
        "max_attempts": retries + 1,
    }


def _normalize_ws_payload(payload) -> list[dict]:
    """
    支持以下输入：
    1) {"name": "...", "link": "..."}
    2) [{"name": "...", "link": "..."}, ...]
    3) {"videos":[...]} 或 {"data": {.../[]}}
    """
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if "name" in payload and "link" in payload:
            return [payload]
        for key in ("videos", "data", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return [v]
    return []


def run_file_mode(config_items: list[dict] | None = None):
    """
    文件批量模式：默认读取 videos.json；若传入 config_items（例如命令行 --url），则只处理这些条目。
    """
    ensure_dirs()
    config = config_items if config_items is not None else load_config()

    for item in config:
        name = item.get("name")
        link = item.get("link")
        if not name or not link:
            print(f"跳过无效配置: {item}")
            continue

        print(f"\n{'='*40}")
        print(f"处理视频：{name}")
        print(f"链接：{link}")
        print(f"{'='*40}")

        # 若 output 中已存在该名称的成品稿，则跳过
        output_file = OUTPUT_DIR / f"{name}.txt"
        if output_file.exists():
            print(f"✅ 已存在，跳过：{output_file}")
            continue

        try:
            result = process_item_with_retry(item, retries=3)
            if result.get("status") == "success":
                print(f"✅ 处理完成：{name}")
            else:
                print(f"[ERROR] 处理 {name} 失败：{result.get('error')}")
        except Exception as e:
            print(f"[ERROR] 处理 {name} 失败：{e}")


async def run_realtime_mode(host: str, port: int):
    """
    实时模式：
    - 启动 WebSocket 服务
    - 接收类似 videos.json 结构的消息
    - 入队串行处理（默认不并发）
    - 处理完成后回传：原结构 + 文字稿/状态
    """
    ensure_dirs()
    task_queue: asyncio.Queue[tuple[object, dict]] = asyncio.Queue()

    async def worker():
        while True:
            websocket, item = await task_queue.get()
            try:
                result = await asyncio.to_thread(process_item_with_retry, item, 3)
                await websocket.send(json.dumps(result, ensure_ascii=False))
            except Exception as e:
                err = {
                    **item,
                    "status": "error",
                    "error": str(e),
                }
                try:
                    await websocket.send(json.dumps(err, ensure_ascii=False))
                except Exception:
                    pass
            finally:
                task_queue.task_done()

    async def ws_handler(websocket):
        async for message in websocket:
            try:
                payload = json.loads(message)
            except Exception:
                await websocket.send(
                    json.dumps({"status": "error", "error": "消息不是合法 JSON"}, ensure_ascii=False)
                )
                continue

            items = _normalize_ws_payload(payload)
            if not items:
                await websocket.send(
                    json.dumps(
                        {
                            "status": "error",
                            "error": "消息结构不符合要求，需包含 name/link 或 videos/data 列表",
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            for item in items:
                await task_queue.put((websocket, item))
            await websocket.send(
                json.dumps(
                    {
                        "status": "queued",
                        "queued_count": len(items),
                        "queue_size": task_queue.qsize(),
                    },
                    ensure_ascii=False,
                )
            )

    worker_task = asyncio.create_task(worker())
    print(f"🚀 WebSocket 实时服务已启动：ws://{host}:{port}")
    print("   收到消息后将按队列串行处理，完成后回传结果。")
    try:
        async with websockets.serve(ws_handler, host, port, max_size=8 * 1024 * 1024):
            await asyncio.Future()
    finally:
        worker_task.cancel()


def _build_cli_file_items(urls: list[str], names: list[str] | None) -> list[dict]:
    """从命令行 --url / --name 构造与 videos.json 同结构的列表。"""
    if not urls:
        return []
    names = names or []
    if len(names) > len(urls):
        raise ValueError("--name 数量不能多于 --url")
    items = []
    for i, link in enumerate(urls):
        if i < len(names):
            name = names[i]
        else:
            name = f"cli_{i + 1:03d}"
        items.append({"name": name, "link": link})
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whisper 无下载批量/实时转写")
    parser.add_argument("--mode", choices=["file", "realtime"], default="file", help="运行模式")
    parser.add_argument("--host", default=REALTIME_HOST, help="realtime 模式监听地址")
    parser.add_argument("--port", type=int, default=REALTIME_PORT, help="realtime 模式监听端口")
    parser.add_argument(
        "--url",
        action="append",
        dest="cli_urls",
        metavar="LINK",
        help="视频/音频页面链接（与 videos.json 的 link 相同），可多次指定；指定后 file 模式不再读取 videos.json",
    )
    parser.add_argument(
        "--name",
        action="append",
        dest="cli_names",
        metavar="NAME",
        help="与 --url 一一对应的名称（可选）；省略时自动使用 cli_001、cli_002 …",
    )
    args = parser.parse_args()

    if args.mode == "file":
        if args.cli_urls:
            try:
                cli_items = _build_cli_file_items(args.cli_urls, args.cli_names)
            except ValueError as e:
                print(f"参数错误: {e}")
                raise SystemExit(2) from e
            run_file_mode(cli_items)
        else:
            run_file_mode()
    else:
        if args.cli_urls or args.cli_names:
            print("提示: realtime 模式不使用 --url/--name，请通过 WebSocket 推送任务。")
        asyncio.run(run_realtime_mode(args.host, args.port))
