#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新 videos.json 中的 title 和 shottitle 字段
从视频链接获取标题信息
"""

import json
import re
import sys
from pathlib import Path
import subprocess

# 设置 Windows 控制台编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

CONFIG_PATH = Path(__file__).parent.parent / "videos.json"


def get_video_title_ytdlp(link: str) -> str:
    """使用 yt-dlp 获取视频标题"""
    try:
        cmd = [
            "yt-dlp",
            "--get-title",
            "--no-warnings",
            "--no-playlist",
            link
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0:
            title = result.stdout.strip()
            # 移除可能的警告信息
            lines = [line for line in title.split('\n') if line.strip() and not line.startswith('WARNING')]
            if lines:
                return lines[-1]  # 取最后一行（通常是标题）
    except subprocess.TimeoutExpired:
        print(f"  警告: 获取标题超时")
    except Exception as e:
        print(f"  警告: 无法使用 yt-dlp 获取标题: {e}")
    return ""


def update_videos_json():
    """更新 videos.json，为每个视频添加 title 和 shottitle"""
    if not CONFIG_PATH.exists():
        print(f"错误: 文件不存在 {CONFIG_PATH}")
        return

    # 读取现有配置
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        videos = json.load(f)

    print(f"找到 {len(videos)} 个视频，开始更新标题...\n")

    updated = False
    for i, video in enumerate(videos, 1):
        name = video.get("name", "")
        link = video.get("link", "")
        existing_title = video.get("title", "")
        existing_shottitle = video.get("shottitle", "")

        print(f"[{i}/{len(videos)}] {name}")
        print(f"  链接: {link}")

        # 如果已经有 title 和 shottitle，跳过
        if existing_title and existing_shottitle:
            print(f"  已有标题: {existing_title[:50]}...")
            print()
            continue

        # 获取标题
        title = existing_title
        if not title:
            print("  正在获取标题...")
            title = get_video_title_ytdlp(link)
            if not title:
                print("  ⚠️  无法获取标题，请手动填写")
                title = ""
            else:
                print(f"  ✅ 获取到标题: {title[:80]}...")

        # 生成 shottitle
        shottitle = existing_shottitle
        if title and not shottitle:
            shottitle = title[:20]

        # 更新视频信息
        if title:
            video["title"] = title
            updated = True
        if shottitle:
            video["shottitle"] = shottitle
            updated = True

        print()

    # 保存更新
    if updated:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)
        print("videos.json 已更新！")
    else:
        print("没有需要更新的内容")


if __name__ == "__main__":
    try:
        update_videos_json()
    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

