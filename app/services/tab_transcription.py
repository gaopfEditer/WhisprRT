"""
Chrome 多页签实时转写：每个 WebSocket 连接对应一个页签会话。
音频由扩展经 tabCapture 推送（16kHz float32 PCM），与本机麦克风转写互不影响。
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any

import numpy as np
from fastapi import WebSocket

from app.config import ANTI_HALLUCINATION_CONFIG, BUFFER_SECONDS, HALLUCINATION_PATTERNS, SAMPLE_RATE
from app.core.logging import logger
from app.services.whisper import whisper_service

# 多路页签共用同一 Whisper 模型时串行推理，避免并发踩踏
_whisper_lock = threading.Lock()


class TabTranscriptionSession:
    """单个页签的缓冲 + 定时推理会话。"""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        tab_id: str,
        title: str = "",
        language: str = "zh",
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.websocket = websocket
        self.tab_id = tab_id
        self.title = title or f"tab-{tab_id}"
        self.language = language if language != "auto" else None
        self.buffer = np.empty((0,), dtype=np.float32)
        self.lock = threading.Lock()
        self.running = True
        self.start_time = time.time()
        self.last_flush = time.time()
        self._worker: threading.Thread | None = None
        self._loop = loop

        self.energy_threshold = ANTI_HALLUCINATION_CONFIG["energy_threshold"]
        self.confidence_threshold = ANTI_HALLUCINATION_CONFIG["confidence_threshold"]
        self.silence_threshold = ANTI_HALLUCINATION_CONFIG["silence_threshold"]

    def start(self) -> None:
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
        self._worker = threading.Thread(target=self._loop_worker, daemon=True, name=f"tab-asr-{self.tab_id}")
        self._worker.start()

    def stop(self) -> None:
        self.running = False

    def push_pcm(self, samples: np.ndarray) -> None:
        if not self.running or samples.size == 0:
            return
        with self.lock:
            self.buffer = np.concatenate([self.buffer, samples.astype(np.float32, copy=False)])

    def _is_silence(self, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return True
        energy = float(np.mean(np.abs(audio)))
        return energy < max(self.silence_threshold, self.energy_threshold * 0.5)

    def _elapsed_ts(self) -> str:
        elapsed = int(time.time() - self.start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _send_sync(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        loop = self._loop
        if loop is None or loop.is_closed():
            self.running = False
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.websocket.send_json(payload), loop)
            fut.result(timeout=5)
        except Exception as e:
            logger.debug("页签会话发送失败 tab=%s: %s", self.tab_id, e)
            self.running = False

    def _flush_once(self) -> None:
        with self.lock:
            if self.buffer.size < SAMPLE_RATE // 2:
                return
            samples = self.buffer.copy()
            self.buffer = np.empty((0,), dtype=np.float32)
            self.last_flush = time.time()

        if self._is_silence(samples):
            return

        peak = float(np.max(np.abs(samples)))
        if peak > 0:
            samples = (samples / peak).astype(np.float32)

        try:
            with _whisper_lock:
                segments, _ = whisper_service.transcribe(samples, self.language or "zh")
                segments_list = list(segments)
        except Exception as e:
            logger.error("页签转写失败 tab=%s: %s", self.tab_id, e)
            self._send_sync("error", {"message": str(e), "tab_id": self.tab_id})
            return

        for seg in segments_list:
            text = (seg.text or "").strip()
            if not text:
                continue
            confidence = float(np.exp(seg.avg_logprob))
            if confidence < self.confidence_threshold and len(text) < 4:
                continue
            if any(re.search(p, text, re.IGNORECASE) for p in HALLUCINATION_PATTERNS):
                continue
            self._send_sync(
                "transcription",
                {
                    "tab_id": self.tab_id,
                    "title": self.title,
                    "text": text,
                    "timestamp": self._elapsed_ts(),
                    "confidence": confidence,
                },
            )
            logger.info("页签转写 [%s] %s", self.tab_id, text[:80])

    def _loop_worker(self) -> None:
        logger.info("页签转写会话启动 tab=%s title=%s", self.tab_id, self.title)
        while self.running:
            try:
                if time.time() - self.last_flush >= BUFFER_SECONDS:
                    self._flush_once()
                else:
                    time.sleep(0.15)
            except Exception as e:
                logger.error("页签转写循环异常 tab=%s: %s", self.tab_id, e)
                time.sleep(0.5)
        try:
            self._flush_once()
        except Exception:
            pass
        logger.info("页签转写会话结束 tab=%s", self.tab_id)
