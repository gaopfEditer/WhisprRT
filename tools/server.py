#!/usr/bin/env python3
"""
本地服务器，用于 Chrome 插件直接写入 videos.json
运行: python server.py
"""

import json
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# 配置文件路径（相对于项目根目录）
CONFIG_PATH = Path(__file__).parent.parent / "videos.json"
PORT = 8765


class VideoHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """获取当前 videos.json 内容"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = []
            
            response = {
                "success": True,
                "count": len(data),
                "videos": data
            }
        except Exception as e:
            response = {
                "success": False,
                "error": str(e)
            }

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        """添加视频到 videos.json"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json; charset=utf-8")

        try:
            # 读取请求体
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            name = data.get("name", "").strip()
            link = data.get("link", "").strip()
            title = data.get("title", "").strip()
            shottitle = data.get("shottitle", "").strip()

            if not name or not link:
                self.send_response(400)
                self.end_headers()
                response = {"success": False, "error": "name 和 link 不能为空"}
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                return
            
            # 如果没有提供shottitle，从title生成
            if not shottitle and title:
                shottitle = title[:20]

            # 读取现有配置
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    videos = json.load(f)
            else:
                videos = []

            # 检查是否已存在相同名称或链接的视频
            existing = next(
                (v for v in videos if v.get("name") == name or v.get("link") == link),
                None
            )
            if existing:
                self.send_response(200)
                self.end_headers()
                response = {
                    "success": True,
                    "message": "视频已存在",
                    "count": len(videos),
                    "video": existing
                }
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                return

            # 添加新视频
            new_video = {
                "name": name,
                "link": link
            }
            # 添加title和shottitle字段（如果提供）
            if title:
                new_video["title"] = title
            if shottitle:
                new_video["shottitle"] = shottitle
            videos.append(new_video)

            # 确保目录存在
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(videos, f, ensure_ascii=False, indent=2)

            self.send_response(200)
            self.end_headers()
            response = {
                "success": True,
                "message": "视频已添加",
                "count": len(videos),
                "video": new_video
            }
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            response = {"success": False, "error": "无效的 JSON 格式"}
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            response = {"success": False, "error": str(e)}
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{self.address_string()}] {format % args}")


def run_server():
    """启动服务器"""
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, VideoHandler)
    print(f"🚀 本地服务器已启动")
    print(f"📍 地址: http://localhost:{PORT}")
    print(f"📁 配置文件: {CONFIG_PATH.absolute()}")
    print(f"\n按 Ctrl+C 停止服务器\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()

