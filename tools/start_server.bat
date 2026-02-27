@echo off
chcp 65001 >nul
echo 🚀 启动视频转文字稿本地服务器...
echo.
cd /d %~dp0
python server.py
pause

