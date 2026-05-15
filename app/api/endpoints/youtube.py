"""
YouTube 字幕 HTTP 接口（与前端共用）。
"""
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.youtube_subtitles import fetch_many, fetch_one

router = APIRouter()


class YoutubeSubtitlesRequest(BaseModel):
    """批量拉取字幕（JSON Body）"""

    urls: list[str] = Field(..., min_length=1, description="YouTube 视频链接列表，每行一个也可由前端拆分")
    langs: list[str] | None = Field(
        None,
        description="语言偏好顺序，如 [\"zh-Hans\",\"en\"]。为空时使用 zh / en 等默认顺序。",
    )
    include_segments: bool = Field(True, description="是否在响应中包含分段时间轴")


@router.post("/youtube/subtitles")
def post_youtube_subtitles(body: YoutubeSubtitlesRequest):
    """
    批量拉取多个视频的字幕（推荐）。

    示例：`POST /youtube/subtitles`，Body `{"urls":["https://youtu.be/xxx"],"langs":["en"]}`
    """
    rows = fetch_many(body.urls, body.langs)
    if not body.include_segments:
        for r in rows:
            r.pop("segments", None)
    return {"status": "success", "count": len(rows), "results": rows}


@router.get("/youtube/subtitles")
def get_youtube_subtitles(
    url: str = Query(..., description="单个 YouTube 视频 URL"),
    lang: Annotated[str | None, Query(description="语言偏好，逗号分隔，如 zh-Hans,en")] = None,
    include_segments: bool = Query(True, description="是否包含 segments 数组"),
):
    """
    拉取单个视频字幕（便于 curl / 其它服务调用）。

    示例：`GET /youtube/subtitles?url=https://youtu.be/xxx&lang=zh,en`
    """
    prefs = [s.strip() for s in lang.split(",")] if lang else None
    row = fetch_one(url, prefs)
    if not include_segments:
        row.pop("segments", None)
    return row
