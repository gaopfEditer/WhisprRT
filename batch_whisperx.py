import json
import os
import re
import subprocess
from pathlib import Path

import requests

# 配置文件路径
CONFIG_PATH = Path("videos.json")

# 音频输出目录（可按需修改）
AUDIO_DIR = Path("audios")
# 文字稿输出目录
TRANSCRIPT_DIR = Path("subtitles")

# WhisperX 参数（按你当前稳定可用的命令来）
WHISPER_MODEL = "large-v2"
WHISPER_LANGUAGE = "zh"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_VAD_METHOD = "silero"

# 通义千问（Qwen）配置
QWEN_API_KEY = "sk-40fc3963ae51439db02c07d7b9995042"  # 建议实际使用时从环境变量读取
QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
QWEN_MODEL = "qwen-turbo"


def run_cmd(cmd: list[str], cwd: Path | None = None):
    """运行命令行，实时打印输出，失败时抛异常。"""
    print(f"\n>>> Running: {' '.join(cmd)}")
    # 不抓输出，直接让子进程把日志打到当前控制台，实现流式显示
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with code {result.returncode}: {' '.join(cmd)}")
    return ""


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)


def download_audio(name: str, link: str) -> Path:
    """
    使用 yt-dlp 下载音频为 wav，文件名使用 name.wav
    """
    ensure_dirs()
    # 目标 wav 文件路径，如 audios/zz-video1.wav
    wav_path = AUDIO_DIR / f"{name}.wav"

    # 如果已存在同名 wav，直接复用，避免重复下载
    if wav_path.exists():
        print(f"\n✅ 音频已存在，跳过下载：{wav_path}")
        return wav_path

    # yt-dlp 输出模板
    out_template = str(AUDIO_DIR / f"{name}.%(ext)s")

    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "wav",
        link,
        "-o",
        out_template,
    ]
    run_cmd(cmd)
    if not wav_path.exists():
        raise FileNotFoundError(f"下载后未找到 wav 文件: {wav_path}")
    return wav_path


def transcribe_audio(name: str, wav_path: Path):
    """
    使用 whisperx 生成文字稿，并保存为 subtitles/name.txt
    """
    ensure_dirs()
    transcript_path = TRANSCRIPT_DIR / f"{name}.txt"

    cmd = [
        "whisperx",
        str(wav_path),
        "--model",
        WHISPER_MODEL,
        "--language",
        WHISPER_LANGUAGE,
        "--output_dir",
        str(TRANSCRIPT_DIR),
        "--output_format",
        "txt",
        "--compute_type",
        WHISPER_COMPUTE_TYPE,
        "--vad_method",
        WHISPER_VAD_METHOD,
        "--no_align",  # 禁用词级对齐，避免下载对齐模型
    ]

    # 启动 whisperx 子进程，流式读取 stdout，同时写入文件并打印到控制台
    print(f"\n>>> Transcribing {wav_path} -> {transcript_path}")
    with open(transcript_path, "w", encoding="utf-8") as f:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # 按行读取输出，边打印边写入
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            f.write(line)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"WhisperX 转写失败: {process.returncode}")

    print(f"\n✅ 转写完成：{transcript_path}")

    # 使用 AI 进一步整理断句，生成精排稿
    try:
        refined_path = refine_transcript_with_qwen(name, transcript_path)
        print(f"✅ AI 断句整理完成：{refined_path}")
    except Exception as e:
        print(f"⚠ AI 处理失败（跳过）：{e}")


def extract_plain_text_from_transcript(raw_text: str) -> str:
    """
    从 WhisperX 的 Transcript 行中提取纯文本并合并。
    形如：Transcript: [0.674 --> 28.222] 内容...
    """
    lines = raw_text.splitlines()
    texts: list[str] = []
    pattern = re.compile(r"^Transcript:\s*\[[^\]]+\]\s*(.*)$")
    for line in lines:
        m = pattern.match(line.strip())
        if m:
            content = m.group(1).strip()
            if content:
                texts.append(content)
    # 用换行拼接，便于后续 AI 断句、重排
    return "\n".join(texts)


def call_qwen(prompt: str) -> str:
    """
    调用通义千问 API，对文本进行断句/整理。
    """
    if not QWEN_API_KEY:
        raise RuntimeError("QWEN_API_KEY 未配置")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }

    payload = {
        "model": QWEN_MODEL,
        "input": prompt,
        "parameters": {
            "temperature": 0.7,
            "max_tokens": 2000,
        },
    }

    resp = requests.post(QWEN_ENDPOINT, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # 通义千问返回格式参考官方文档，这里按通用结构读取
    try:
        return data["output"]["text"]
    except Exception:
        # 打印原始返回，方便调试
        raise RuntimeError(f"Qwen 返回解析失败: {data}")


def refine_transcript_with_qwen(name: str, transcript_path: Path) -> Path:
    """
    读取原始 transcript，提取纯文本交给 Qwen，生成断句正确的精排稿。
    """
    raw = transcript_path.read_text(encoding="utf-8")
    plain_text = extract_plain_text_from_transcript(raw)

    if not plain_text.strip():
        raise RuntimeError("原始 transcript 中未提取到有效文本")

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

    prompt = system_prompt + plain_text
    refined_text = call_qwen(prompt)

    refined_path = transcript_path.with_name(f"{name}_refined.txt")
    refined_path.write_text(refined_text, encoding="utf-8")
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

        print(f"\n==============================")
        print(f"处理视频：{name}")
        print(f"链接：{link}")
        print(f"==============================")

        try:
            wav_path = download_audio(name, link)
            transcribe_audio(name, wav_path)
        except Exception as e:
            print(f"❌ 处理 {name} 失败：{e}")


if __name__ == "__main__":
    main()