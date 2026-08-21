"""
Chrome 多页签音频 WebSocket：每连接一路页签 PCM → Whisper。
"""
from urllib.parse import unquote

import asyncio

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import logger
from app.services.tab_transcription import TabTranscriptionSession
from app.services.whisper import whisper_service

router = APIRouter()


@router.websocket("/ws/tab")
async def tab_audio_websocket(websocket: WebSocket):
    """
    协议：
    - 连接：`/ws/tab?tab_id=123&title=...&lang=zh`
    - 客户端发二进制：float32 PCM，16kHz 单声道
    - 客户端也可发 JSON 文本：`{"type":"ping"}` / `{"type":"config","lang":"en"}`
    - 服务端推送：`{event, data}`，转写为 event=transcription
    """
    await websocket.accept()
    q = websocket.query_params
    tab_id = (q.get("tab_id") or "unknown").strip()
    title = unquote((q.get("title") or "").strip())[:200]
    lang = (q.get("lang") or "zh").strip() or "zh"

    session = TabTranscriptionSession(
        websocket,
        tab_id=tab_id,
        title=title,
        language=lang,
        loop=asyncio.get_running_loop(),
    )
    session.start()

    try:
        await websocket.send_json(
            {
                "event": "status",
                "data": {
                    "status": "connected",
                    "tab_id": tab_id,
                    "model": whisper_service.model_name,
                    "language": lang,
                },
            }
        )
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if "bytes" in message and message["bytes"] is not None:
                raw = message["bytes"]
                if len(raw) < 4 or len(raw) % 4 != 0:
                    continue
                samples = np.frombuffer(raw, dtype=np.float32).copy()
                session.push_pcm(samples)
            elif "text" in message and message["text"] is not None:
                text = message["text"]
                if '"ping"' in text:
                    await websocket.send_json({"event": "pong", "data": {"tab_id": tab_id}})
    except WebSocketDisconnect:
        logger.info("页签 WebSocket 断开 tab=%s", tab_id)
    except Exception as e:
        logger.error("页签 WebSocket 异常 tab=%s: %s", tab_id, e)
    finally:
        session.stop()
