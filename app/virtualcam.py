"""
Windows 虚拟摄像头模块（pyvirtualcam）。

依赖：
  pip install pyvirtualcam numpy
  可选：pip install opencv-python  （--source video 时需要）

系统：Windows 需先安装 OBS Studio，并至少打开一次「启动虚拟摄像头」
      以注册 OBS Virtual Camera 驱动。

启动：
  python -m app.virtualcam
  python -m app.virtualcam --width 1280 --height 720 --fps 30
  python -m app.virtualcam --mode pattern
  python -m app.virtualcam --mode video --source path\\to\\video.mp4
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from app.core.logging import logger


def _parse_color(s: str) -> tuple[int, int, int]:
    """解析 RGB，如 0,255,0 或 #00FF00。"""
    s = (s or "").strip()
    if s.startswith("#") and len(s) == 7:
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    parts = [p.strip() for p in s.replace(" ", "").split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("颜色格式应为 R,G,B 或 #RRGGBB")
    rgb = tuple(int(x) for x in parts)
    if any(c < 0 or c > 255 for c in rgb):
        raise argparse.ArgumentTypeError("颜色分量须在 0–255")
    return rgb  # type: ignore[return-value]


def _make_solid_frame(h: int, w: int, color: tuple[int, int, int]) -> np.ndarray:
    frame = np.empty((h, w, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def _make_pattern_frame(h: int, w: int, t: float) -> np.ndarray:
    """简单动态测试图案：色条 + 移动竖线。"""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    # 水平色条
    bands = 6
    colors = [
        (220, 50, 47),
        (255, 180, 0),
        (40, 180, 80),
        (30, 120, 220),
        (160, 60, 200),
        (40, 40, 40),
    ]
    bh = max(1, h // bands)
    for i in range(bands):
        y0, y1 = i * bh, min(h, (i + 1) * bh)
        frame[y0:y1, :] = colors[i % len(colors)]
    # 移动白线
    x = int((t * 120) % max(w, 1))
    x1 = min(w, x + max(2, w // 80))
    frame[:, x:x1] = (255, 255, 255)
    return frame


def _open_video(path: str, width: int, height: int):
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(
            "读取视频需要 opencv-python：pip install opencv-python"
        ) from e
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {path}")
    return cap, cv2


def run_virtual_camera(
    *,
    width: int = 640,
    height: int = 480,
    fps: int = 30,
    mode: str = "color",
    color: tuple[int, int, int] = (0, 255, 0),
    source: str | None = None,
    backend: str | None = None,
    device: str | None = None,
) -> None:
    try:
        import pyvirtualcam
    except ImportError as e:
        raise RuntimeError(
            "未安装 pyvirtualcam。请执行：pip install pyvirtualcam\n"
            "Windows 还需安装 OBS Studio，并在 OBS 中至少启动一次「虚拟摄像头」。"
        ) from e

    cam_kwargs: dict = {
        "width": width,
        "height": height,
        "fps": fps,
    }
    if backend:
        cam_kwargs["backend"] = backend
    if device:
        cam_kwargs["device"] = device

    video_cap = None
    cv2 = None
    if mode == "video":
        if not source:
            raise RuntimeError("--mode video 时必须提供 --source 视频路径")
        video_cap, cv2 = _open_video(source, width, height)

    logger.info(
        "启动虚拟摄像头 width=%s height=%s fps=%s mode=%s",
        width,
        height,
        fps,
        mode,
    )

    try:
        with pyvirtualcam.Camera(**cam_kwargs) as cam:
            print(f"虚拟摄像头已启动: {cam.device}")
            print(f"  分辨率 {cam.width}x{cam.height} @ {cam.fps:.1f} fps, mode={mode}")
            print("  在 Zoom/Teams/浏览器中选择该摄像头即可预览。Ctrl+C 结束。")
            t0 = time.time()
            while True:
                if mode == "color":
                    frame = _make_solid_frame(cam.height, cam.width, color)
                elif mode == "pattern":
                    frame = _make_pattern_frame(cam.height, cam.width, time.time() - t0)
                elif mode == "video":
                    assert video_cap is not None and cv2 is not None
                    ok, bgr = video_cap.read()
                    if not ok:
                        video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, bgr = video_cap.read()
                        if not ok:
                            raise RuntimeError("视频读取失败")
                    bgr = cv2.resize(bgr, (cam.width, cam.height))
                    frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                else:
                    raise RuntimeError(f"未知 mode: {mode}")

                cam.send(frame)
                cam.sleep_until_next_frame()
    except KeyboardInterrupt:
        print("\n已停止虚拟摄像头")
    finally:
        if video_cap is not None:
            video_cap.release()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.virtualcam",
        description="Windows 虚拟摄像头（pyvirtualcam + OBS Virtual Camera）",
    )
    p.add_argument("--width", type=int, default=640, help="宽度，默认 640")
    p.add_argument("--height", type=int, default=480, help="高度，默认 480")
    p.add_argument("--fps", type=int, default=30, help="帧率，默认 30")
    p.add_argument(
        "--mode",
        choices=("color", "pattern", "video"),
        default="color",
        help="画面：color 纯色 / pattern 测试图案 / video 循环视频",
    )
    p.add_argument(
        "--color",
        type=_parse_color,
        default=(0, 255, 0),
        help="纯色 RGB，如 0,255,0 或 #00FF00（仅 mode=color）",
    )
    p.add_argument(
        "--source",
        type=str,
        default=None,
        help="视频文件路径（仅 mode=video）",
    )
    p.add_argument(
        "--backend",
        type=str,
        default=None,
        help="pyvirtualcam 后端，Windows 常用 obs（默认自动）",
    )
    p.add_argument(
        "--device",
        type=str,
        default=None,
        help="指定虚拟设备名（一般可省略）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "video" and args.source:
        if not Path(args.source).is_file():
            print(f"错误：视频不存在: {args.source}", file=sys.stderr)
            return 1
    try:
        run_virtual_camera(
            width=args.width,
            height=args.height,
            fps=args.fps,
            mode=args.mode,
            color=args.color,
            source=args.source,
            backend=args.backend,
            device=args.device,
        )
    except Exception as e:
        logger.error("虚拟摄像头失败: %s", e)
        print(f"错误: {e}", file=sys.stderr)
        if "obs" in str(e).lower() or "backend" in str(e).lower() or "camera" in str(e).lower():
            print(
                "\n提示（Windows）：\n"
                "  1) 安装 OBS Studio：https://obsproject.com/\n"
                "  2) 打开 OBS → 控制栏「启动虚拟摄像头」一次（注册驱动）\n"
                "  3) 再运行本模块；需要时可加 --backend obs\n"
                "  4) pip install -U pyvirtualcam numpy",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
