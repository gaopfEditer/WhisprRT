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

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });
  } catch (e1) {
    // 部分 Chromium 版本不接受 mandatory 写法
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        chromeMediaSource: 'tab',
        chromeMediaSourceId: streamId,
      },
      video: false,
    });
  }

  const ctx = new AudioContext({ sampleRate: 48000 });
  // Offscreen 里常为 suspended，不 resume 则 onaudioprocess 不会触发 → 一直「监听中」无字
  if (ctx.state === 'suspended') {
    await ctx.resume();
  }
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);

  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  await new Promise((resolve, reject) => {
    const t = setTimeout(
      () => reject(new Error('WebSocket 连接超时，请确认 python -m app.main 已启动')),
      8000
    );
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

  let chunksSent = 0;
  processor.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    // 回放原音，避免 tabCapture 静音页签
    e.outputBuffer.getChannelData(0).set(input);
    if (ws.readyState !== WebSocket.OPEN) return;
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
      return;
    }
    const pcm = downsample(input, ctx.sampleRate, 16000);
    ws.send(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength));
    chunksSent += 1;
    if (chunksSent === 1 || chunksSent % 50 === 0) {
      notify({
        type: 'tabStatus',
        tabId,
        status: 'streaming',
        title,
        chunksSent,
      });
    }
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
  // 关键：只认领自己的消息。若对其它消息 sendResponse({error:'ignored'})，
  // Chrome 可能把它当成 popup→startTabs 的唯一响应，界面就会显示 ignored。
  if (msg?.type === 'offscreenPing') {
    sendResponse({ ok: true, pong: true, sessions: sessions.size });
    return false;
  }
  if (msg?.type !== 'offscreenStart' && msg?.type !== 'offscreenStop') {
    return false;
  }

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
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});
