"""
应用包。

注意：不要在此处强制 import FastAPI/Whisper，否则
`python -m app.virtualcam` 等轻量入口也会加载整站。
需要应用实例时使用：`from app.main import app`
"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from app.main import app as _app

        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
