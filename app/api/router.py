"""
API路由注册
"""
from fastapi import APIRouter
from app.api.endpoints import audio, tab_ws, transcription, websocket, youtube

# 创建主路由
api_router = APIRouter()

# 注册各模块路由
api_router.include_router(audio.router, tags=["audio"])
api_router.include_router(transcription.router, tags=["transcription"])
api_router.include_router(websocket.router, tags=["websocket"])
api_router.include_router(youtube.router, tags=["youtube"])
api_router.include_router(tab_ws.router, tags=["tab-transcription"])