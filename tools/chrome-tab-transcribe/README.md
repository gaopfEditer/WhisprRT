# WhisprRT 多页签听写（Chrome）

分别捕获 **N 个 Chrome 页签** 的音频，推送到本机 `python -m app.main`，每路独立出字。

## 使用步骤

1. 启动后端：

```powershell
.venv\Scripts\Activate.ps1
python -m app.main
```

2. Chrome 打开 `chrome://extensions` → 开启「开发者模式」→「加载已解压的扩展程序」→ 选择本目录：

`tools/chrome-tab-transcribe`

3. 打开 2～3 个正在播放声音的页签，点击扩展图标：
   - 勾选要监听的页签
   - 点「开始监听所选」
   - 可点「打开大面板」查看分路文字

## 说明

- 依赖 Chrome `tabCapture` + Offscreen Document，**仅 Chrome / 基于 Chromium 且支持该 API 的浏览器**。
- 每路连接：`ws://127.0.0.1:5444/ws/tab?tab_id=...&title=...&lang=zh`
- 多路共用同一 Whisper 模型并**串行推理**，页签越多，单路延迟可能越高。
- `chrome://`、扩展页等无法捕获。
- 捕获时会通过 AudioContext 回放，避免页签被静音。
