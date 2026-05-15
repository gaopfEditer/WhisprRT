"""
YouTube 字幕拉取（yt-dlp）：供 Web 页与 HTTP 接口复用。
Cookie 与环境变量与批处理脚本约定一致：YOUTUBE_COOKIES_FILE、项目根 youtube_cookies.txt、
可选 D:\\frontend\\main\\tools\\youtube_cookies.txt、YOUTUBE_COOKIES_FROM_BROWSER。
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.request import Request

import yt_dlp

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DEFAULT_COOKIE = Path(r"D:\frontend\main\tools\youtube_cookies.txt")

_SUBTITLE_FORMAT_ORDER = ("json3", "srv3", "srv1", "vtt", "ttml", "srt")


def _merge_youtube_ydl_opts(base: dict[str, Any]) -> dict[str, Any]:
    opts = {**base}
    cookie_file = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if not cookie_file:
        for candidate in (
            PROJECT_ROOT / "youtube_cookies.txt",
            PROJECT_ROOT / "macstudioyoutube.com_cookies.txt",
        ):
            if candidate.is_file():
                cookie_file = str(candidate)
                break
    if not cookie_file and _TOOLS_DEFAULT_COOKIE.is_file():
        cookie_file = str(_TOOLS_DEFAULT_COOKIE)
    if cookie_file and Path(cookie_file).is_file():
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

    ex = dict(opts.get("extractor_args") or {})
    yt = dict(ex.get("youtube") or {})
    if not yt.get("player_client"):
        yt["player_client"] = ["android", "web", "ios"]
    ex["youtube"] = yt
    opts["extractor_args"] = ex
    return opts


def _is_youtube_url(url: str) -> bool:
    low = (url or "").lower().strip()
    return "youtube.com" in low or "youtu.be" in low or "m.youtube.com" in low


def _lang_match_score(lang_code: str, preference: str) -> int:
    lc = lang_code.lower().replace("_", "-")
    pref = preference.lower().replace("_", "-")
    if lc == pref:
        return 100
    if lc.startswith(pref) or pref.startswith(lc):
        return 80
    base = pref.split("-")[0]
    if lc.split("-")[0] == base:
        return 60
    return 0


def _pick_language(available: list[str], preferences: list[str]) -> str | None:
    if not available:
        return None
    best: tuple[int, str] | None = None
    for lang in available:
        score = 0
        for pref in preferences:
            score = max(score, _lang_match_score(lang, pref))
        if score > 0:
            cand = (score, lang)
            best = cand if best is None or cand > best else best
    if best:
        return best[1]
    return available[0]


def _collect_subtitle_languages(info: dict[str, Any]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    manual = dict(info.get("subtitles") or {})
    automatic = dict(info.get("automatic_captions") or {})
    return manual, automatic


def _pick_format_entry(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_ext = {str(f.get("ext") or ""): f for f in formats if f.get("url")}
    for ext in _SUBTITLE_FORMAT_ORDER:
        if ext in by_ext:
            return by_ext[ext]
    for f in formats:
        if f.get("url"):
            return f
    return None


def _parse_json3(raw: str) -> tuple[list[dict[str, Any]], str]:
    data = json.loads(raw)
    segments: list[dict[str, Any]] = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        start_ms = ev.get("tStartMs", 0) or 0
        dur_ms = ev.get("dDurationMs") or 0
        start = float(start_ms) / 1000.0
        dur = float(dur_ms) / 1000.0
        text = "".join(s.get("utf8", "") for s in segs if isinstance(s, dict))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        end = start + dur if dur > 0 else start
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    plain = "\n".join(s["text"] for s in segments)
    return segments, plain


def _parse_srv_xml(raw: str) -> tuple[list[dict[str, Any]], str]:
    segments: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<text\s+start="([\d.]+)"(?:\s+dur="([\d.]+)")?[^>]*>([\s\S]*?)</text>',
        re.I,
    )
    for m in pattern.finditer(raw):
        start = float(m.group(1))
        dur = float(m.group(2) or 0)
        inner = html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))
        text = re.sub(r"\s+", " ", inner).strip()
        if not text:
            continue
        end = start + dur if dur > 0 else start
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    plain = "\n".join(s["text"] for s in segments)
    return segments, plain


def _parse_vtt(raw: str) -> tuple[list[dict[str, Any]], str]:
    lines = []
    blocks = re.split(r"\n\n+", raw.strip())
    segments: list[dict[str, Any]] = []
    time_re = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})"
    )

    def ts_to_sec(ts: str) -> float:
        parts = ts.strip().split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])

    for block in blocks:
        if block.upper().startswith("WEBVTT"):
            continue
        m = time_re.search(block)
        if not m:
            continue
        start = ts_to_sec(m.group(1))
        end = ts_to_sec(m.group(2))
        text = time_re.sub("", block, count=1).strip()
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text.startswith("NOTE"):
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        lines.append(text)
    return segments, "\n".join(lines)


def _read_subtitle_body(ydl: yt_dlp.YoutubeDL, fmt: dict[str, Any]) -> tuple[str, str]:
    url = fmt.get("url")
    if not url:
        raise ValueError("字幕条目缺少 url")
    ext = str(fmt.get("ext") or "vtt")
    raw_bytes = ydl.urlopen(Request(url)).read()
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw_bytes.decode("utf-8", errors="replace")
    return raw, ext


def fetch_one(
    url: str,
    lang_preferences: list[str] | None = None,
) -> dict[str, Any]:
    """
    拉取单个 YouTube 链接的字幕。

    Returns:
        dict: url, status, title, video_id, language, is_automatic, subtitle_format,
              segments, text, error_message
    """
    prefs = lang_preferences if lang_preferences else ["zh", "zh-Hans", "zh-Hant", "zh-CN", "en"]
    out: dict[str, Any] = {
        "url": url.strip(),
        "status": "error",
        "title": None,
        "video_id": None,
        "language": None,
        "is_automatic": None,
        "subtitle_format": None,
        "segments": [],
        "text": "",
        "error_message": None,
    }
    u = url.strip()
    if not u:
        out["error_message"] = "空链接"
        return out
    if not _is_youtube_url(u):
        out["error_message"] = "非 YouTube 链接（仅支持 youtube.com / youtu.be）"
        return out

    base_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    ydl_opts = _merge_youtube_ydl_opts(base_opts)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(u, download=False)
            if not isinstance(info, dict):
                out["error_message"] = "无法解析视频信息"
                return out

            out["title"] = info.get("title")
            out["video_id"] = info.get("id")
            if info.get("_type") == "playlist":
                out["error_message"] = "请提供单个视频链接，而非播放列表"
                return out

            manual, automatic = _collect_subtitle_languages(info)
            all_manual = list(manual.keys())
            all_auto = list(automatic.keys())

            chosen_lang: str | None = None
            is_auto = False
            fmts: list[dict[str, Any]] | None = None

            if all_manual:
                chosen_lang = _pick_language(all_manual, prefs)
                if chosen_lang:
                    fmts = manual.get(chosen_lang) or []
            if not fmts and all_auto:
                is_auto = True
                chosen_lang = _pick_language(all_auto, prefs)
                if chosen_lang:
                    fmts = automatic.get(chosen_lang) or []

            if not fmts or not chosen_lang:
                out["error_message"] = (
                    "未找到可用字幕（无人工字幕且无自动字幕，或语言不匹配）。"
                    "可尝试换 lang 参数，或为需登录的视频配置 Cookie。"
                )
                return out

            fmt_entry = _pick_format_entry(fmts)
            if not fmt_entry:
                out["error_message"] = "字幕格式列表为空"
                return out

            raw, ext = _read_subtitle_body(ydl, fmt_entry)
            out["language"] = chosen_lang
            out["is_automatic"] = is_auto
            out["subtitle_format"] = ext

            segments: list[dict[str, Any]] = []
            plain = ""
            if ext == "json3":
                segments, plain = _parse_json3(raw)
            elif ext in ("srv1", "srv3"):
                segments, plain = _parse_srv_xml(raw)
                if not plain and raw.lstrip().startswith("WEBVTT"):
                    segments, plain = _parse_vtt(raw)
            elif ext == "vtt":
                segments, plain = _parse_vtt(raw)
            else:
                plain = re.sub(r"\s+", " ", raw).strip()
                segments = [{"start": 0.0, "end": 0.0, "text": plain}]

            out["segments"] = segments
            out["text"] = plain
            out["status"] = "ok"
            return out

    except Exception as e:
        logger.exception("YouTube 字幕拉取失败: %s", u)
        out["error_message"] = str(e)
        return out


def fetch_many(urls: list[str], lang_preferences: list[str] | None = None) -> list[dict[str, Any]]:
    return [fetch_one(u, lang_preferences) for u in urls]
