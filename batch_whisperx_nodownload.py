"""
批量流式转写脚本 - 无需下载，直接获取 URL 音视频流并转写中文字稿

技术方案：yt-dlp 获取真实流地址 → FFmpeg 管道转 16k 单声道 PCM → faster-whisper 推理
配置文件：videos.json（与 batch_whisperx 共用）

依赖：yt-dlp, ffmpeg, faster-whisper, numpy, requests
  pip install yt-dlp faster-whisper numpy requests
"""
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import requests
import yt_dlp
from faster_whisper import WhisperModel

# 配置文件路径（与 batch_whisperx 共用）
CONFIG_PATH = Path("videos.json")

# 输出目录
TRANSCRIPT_DIR = Path("subtitles")
LOG_DIR = Path("logs")
OUTPUT_DIR = Path("output")

# faster-whisper 参数
WHISPER_MODEL = "large-v3-turbo"
WHISPER_LANGUAGE = "zh"

def _detect_device():
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"

WHISPER_DEVICE = _detect_device()
WHISPER_COMPUTE_TYPE = "float16" if WHISPER_DEVICE == "cuda" else "int8"

# 通义千问配置（与 batch_whisperx 相同）
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "sk-40fc3963ae51439db02c07d7b9995042")
QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
QWEN_MODEL = "qwen-turbo"

# 全局模型实例（避免每次重复加载）
_whisper_model: WhisperModel | None = None


def get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        print(f"\n>>> 加载 Whisper 模型: {WHISPER_MODEL} ({WHISPER_DEVICE})")
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


def get_stream_url(link: str) -> str:
    """使用 yt-dlp 获取音视频流的真实 URL，不下载"""
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=False)
        if info is None:
            raise RuntimeError(f"无法获取视频信息: {link}")
        # 优先使用 info['url']（yt-dlp 解析后的直接链接）
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
        return url


def stream_to_audio_array(stream_url: str) -> np.ndarray:
    """
    使用 FFmpeg 将流转为 16kHz 单声道 float32 数组（Whisper 所需格式）
    输出到 stdout，Python 读取并转换
    """
    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-i", stream_url,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-",
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    raw_bytes, stderr = process.communicate()
    if process.returncode != 0:
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        raise RuntimeError(f"FFmpeg 转码失败 (code={process.returncode}): {err}")

    if len(raw_bytes) == 0:
        raise RuntimeError("FFmpeg 未输出任何数据，可能流地址无效或视频无音轨")

    # int16 -> float32, 范围 [-1, 1]
    audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def transcribe_audio_array(audio: np.ndarray) -> list[tuple[float, float, str]]:
    """使用 faster-whisper 转写，返回 [(start, end, text), ...]"""
    model = get_whisper_model()
    segments, _ = model.transcribe(
        audio,
        language=WHISPER_LANGUAGE,
        beam_size=1,
        vad_filter=True,
    )
    result = []
    for seg in segments:
        result.append((seg.start, seg.end, (seg.text or "").strip()))
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
    stream_url = get_stream_url(link)

    print(f">>> FFmpeg 转码中（16k 单声道）...")
    audio = stream_to_audio_array(stream_url)
    duration_sec = len(audio) / 16000
    print(f"    音频时长约 {duration_sec:.1f} 秒")

    print(f">>> Transcribing -> {transcript_path}")
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


def main():
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

        try:
            transcript_path = stream_transcribe(name, link)
            try:
                refined_path = refine_transcript_with_qwen(name, transcript_path)
                print(f"✅ AI 断句整理完成：{refined_path}")
            except Exception as e:
                print(f"⚠ AI 处理失败（跳过）：{e}")
        except Exception as e:
            print(f"[ERROR] 处理 {name} 失败：{e}")


if __name__ == "__main__":
    main()
