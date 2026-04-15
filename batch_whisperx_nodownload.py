"""
批量流式转写脚本 - 无需下载，直接获取 URL 音视频流并转写中文字稿

技术方案：yt-dlp 获取真实流地址 → FFmpeg 管道转 16k 单声道 PCM → faster-whisper 推理
配置文件：videos.json（与 batch_whisperx 共用）

依赖：yt-dlp, ffmpeg, faster-whisper, numpy, requests
  pip install yt-dlp faster-whisper numpy requests

若报错 cudnn_ops64_9.dll / cudnnCreateTensorDescriptor：说明缺 cuDNN 或未加入 PATH，
  可强制用 CPU 运行（较慢但无需 GPU）：运行前设置环境变量 USE_CPU=1
  PowerShell: $env:USE_CPU="1"; python batch_whisperx_nodownload.py
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


def _is_cuda_runtime_missing_error(e: BaseException) -> bool:
    msg = str(e).lower()
    keys = (
        "cublas64_12.dll",
        "cudnn",
        "cublas",
        "cuda runtime",
        "cannot be loaded",
        "is not found",
    )
    return any(k in msg for k in keys)


def get_whisper_model() -> WhisperModel:
    global _whisper_model, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
    if _whisper_model is None:
        print(f"\n>>> 加载 Whisper 模型: {WHISPER_MODEL} ({WHISPER_DEVICE}, {WHISPER_COMPUTE_TYPE})")
        try:
            _whisper_model = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        except Exception as e:
            if WHISPER_DEVICE == "cuda" and _is_cuda_runtime_missing_error(e):
                print("⚠ CUDA 运行库缺失，自动回退到 CPU 模式继续本次任务。")
                WHISPER_DEVICE = "cpu"
                WHISPER_COMPUTE_TYPE = "int8"
                _whisper_model = WhisperModel(
                    WHISPER_MODEL,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
            else:
                raise
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


def get_stream_url(link: str) -> tuple[str, float | None]:
    """使用 yt-dlp 获取音视频流的真实 URL 与时长（秒），不下载。返回 (url, duration_sec)，duration 可能为 None。"""
    ydl_opts = {
        "format": "bestaudio/best",
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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=False)
        if info is None:
            raise RuntimeError(f"无法获取视频信息: {link}")
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
        if not url:
            raise RuntimeError(f"无法获取流地址: {link}")
        duration = info.get("duration")
        return (url, float(duration) if duration is not None else None)


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
            if _is_cuda_runtime_missing_error(e):
                print("[ERROR] 检测到 CUDA 运行库缺失，属于环境问题，不再重复重试当前任务。")
                break
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


def run_file_mode():
    ensure_dirs()
    config = load_config()

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whisper 无下载批量/实时转写")
    parser.add_argument("--mode", choices=["file", "realtime"], default="file", help="运行模式")
    parser.add_argument("--host", default=REALTIME_HOST, help="realtime 模式监听地址")
    parser.add_argument("--port", type=int, default=REALTIME_PORT, help="realtime 模式监听端口")
    args = parser.parse_args()

    if args.mode == "file":
        run_file_mode()
    else:
        asyncio.run(run_realtime_mode(args.host, args.port))
