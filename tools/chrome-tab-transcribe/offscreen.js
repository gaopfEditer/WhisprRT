/**
 * Offscreen：对每个页签 getUserMedia(tab) → 降采样 16k → WebSocket 推 float32 PCM。
 */

/** @type {Map<number, {stream: MediaStream, ctx: AudioContext, processor: ScriptProcessorNode, source: MediaStreamAudioSourceNode, ws: WebSocket, title: string}>} */
const sessions = new Map();

function downsample(float32, inRate, outRate) {
  if (inRate === outRate) return float32;
  const ratio = inRate / outRate;
  const outLen = Math.max(1, Math.floor(float32.length / ratio));
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    out[i] = float32[Math.floor(i * ratio)] || 0;
  }
  return out;
}

function notify(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

async function startSession({ tabId, streamId, wsUrl, title }) {
  if (sessions.has(tabId)) {
    await stopSession(tabId);
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: 'tab',
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  // 4096 ~ 85ms @48k；缓冲由后端按 BUFFER_SECONDS 聚合
  const processor = ctx.createScriptProcessor(4096, 1, 1);

  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('WebSocket 连接超时，请确认 python -m app.main 已启动')), 8000);
    ws.onopen = () => {
      clearTimeout(t);
      resolve();
    };
    ws.onerror = () => {
      clearTimeout(t);
      reject(new Error('无法连接 WhisprRT WebSocket（ws://127.0.0.1:5444）'));
    };
  });

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.event === 'transcription') {
        notify({
          type: 'transcription',
          tabId,
          title: title || msg.data?.title,
          data: msg.data,
        });
      } else if (msg.event === 'error') {
        notify({
          type: 'tabError',
          tabId,
          error: msg.data?.message || '转写错误',
        });
      } else if (msg.event === 'status') {
        notify({ type: 'tabStatus', tabId, status: msg.data?.status || 'ok', data: msg.data });
      }
    } catch (_) {
      /* ignore */
    }
  };

  ws.onclose = () => {
    notify({ type: 'tabStatus', tabId, status: 'stopped' });
    stopSession(tabId, { skipWs: true });
  };

  processor.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    // 回放原音，避免 tabCapture 静音页签
    e.outputBuffer.getChannelData(0).set(input);
    if (ws.readyState !== WebSocket.OPEN) return;
    const pcm = downsample(input, ctx.sampleRate, 16000);
    ws.send(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength));
  };

  source.connect(processor);
  processor.connect(ctx.destination);

  sessions.set(tabId, { stream, ctx, processor, source, ws, title });
  notify({ type: 'tabStatus', tabId, status: 'listening', title });
}

async function stopSession(tabId, opts = {}) {
  const s = sessions.get(tabId);
  if (!s) return;
  sessions.delete(tabId);
  try {
    s.processor.disconnect();
  } catch (_) {}
  try {
    s.source.disconnect();
  } catch (_) {}
  try {
    s.stream.getTracks().forEach((t) => t.stop());
  } catch (_) {}
  try {
    await s.ctx.close();
  } catch (_) {}
  if (!opts.skipWs) {
    try {
      s.ws.close();
    } catch (_) {}
  }
  notify({ type: 'tabStatus', tabId, status: 'stopped' });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'offscreenStart') {
        await startSession(msg);
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === 'offscreenStop') {
        await stopSession(msg.tabId);
        sendResponse({ ok: true });
        return;
      }
      sendResponse({ ok: false, error: 'ignored' });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});
