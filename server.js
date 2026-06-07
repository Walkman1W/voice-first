const express = require('express');
const cors = require('cors');
const path = require('path');
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');

const app = express();
const PORT = process.env.PORT || 3000;

const GATEWAY_URL = process.env.OPENCLAW_GATEWAY_URL || 'http://127.0.0.1:18789';
const GATEWAY_TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || '89511f3f33f4255def0cfc032175a56bcb2c1c1e09dad63e';
const TTS_VOICE = process.env.TTS_VOICE || 'zh-CN-XiaoxiaoNeural';
const EDGE_TTS_BIN = process.env.EDGE_TTS_BIN || 'edge-tts';

// Ensure ~/.local/bin is in PATH for edge-tts
const homedir = require('os').homedir();
if (!process.env.PATH.includes(`${homedir}/.local/bin`)) {
  process.env.PATH = `${homedir}/.local/bin:${process.env.PATH}`;
}

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// AI 对话 - 流式 SSE
app.post('/api/chat/stream', async (req, res) => {
  const { message, history } = req.body;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  try {
    const response = await fetch(`${GATEWAY_URL}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${GATEWAY_TOKEN}`
      },
      body: JSON.stringify({
        model: 'openclaw/default',
        messages: [
          { role: 'system', content: '你是小龙虾，一个友好、活泼的AI语音助手。回答尽量简洁明了，适合语音播报，不超过3句话。不要使用 markdown 格式或特殊符号。' },
          ...(history || []),
          { role: 'user', content: message }
        ],
        max_tokens: 500,
        stream: true
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      res.write(`data: ${JSON.stringify({ error: `Gateway ${response.status}: ${errText.slice(0, 200)}` })}\n\n`);
      res.write('data: [DONE]\n\n');
      res.end();
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data: ')) continue;
        const payload = trimmed.slice(6);

        if (payload === '[DONE]') {
          res.write(`data: ${JSON.stringify({ done: true, fullText })}\n\n`);
          continue;
        }

        try {
          const parsed = JSON.parse(payload);
          const delta = parsed.choices?.[0]?.delta?.content;
          if (delta) {
            fullText += delta;
            res.write(`data: ${JSON.stringify({ delta, fullText })}\n\n`);
          }
        } catch {}
      }
    }

    res.write('data: [DONE]\n\n');
    res.end();
  } catch (error) {
    console.error('Stream chat error:', error.message);
    res.write(`data: ${JSON.stringify({ error: error.message })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
  }
});

// AI 对话 - 非流式 (兼容)
app.post('/api/chat', async (req, res) => {
  const { message, history } = req.body;

  try {
    const response = await fetch(`${GATEWAY_URL}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${GATEWAY_TOKEN}`
      },
      body: JSON.stringify({
        model: 'openclaw/default',
        messages: [
          { role: 'system', content: '你是小龙虾，一个友好、活泼的AI语音助手。回答尽量简洁明了，适合语音播报，不超过3句话。不要使用 markdown 格式或特殊符号。' },
          ...(history || []),
          { role: 'user', content: message }
        ],
        max_tokens: 300,
        stream: false
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Gateway ${response.status}: ${errText.slice(0, 200)}`);
    }

    const data = await response.json();
    const reply = data.choices?.[0]?.message?.content || '抱歉，我没有获取到回复。';
    res.json({ reply });
  } catch (error) {
    console.error('Chat error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// TTS - 流式 (chunked transfer)
// edge-tts 目前是先生成再返回; 未来 mimo-v2.5-tts 可做真正实时流式
app.post('/api/tts/stream', async (req, res) => {
  const { text } = req.body;
  if (!text || !text.trim()) {
    return res.status(400).json({ error: 'text is required' });
  }

  const tmpFile = path.join(os.tmpdir(), `tts-stream-${Date.now()}.mp3`);

  try {
    await new Promise((resolve, reject) => {
      execFile('edge-tts', [
        '--text', text.slice(0, 500),
        '--voice', TTS_VOICE,
        '--write-media', tmpFile
      ], { timeout: 30000 }, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });

    res.setHeader('Content-Type', 'audio/mpeg');
    res.setHeader('Cache-Control', 'no-cache');

    const stream = fs.createReadStream(tmpFile);
    stream.pipe(res);
    stream.on('end', () => {
      fs.unlink(tmpFile, () => {});
    });
    stream.on('error', () => {
      fs.unlink(tmpFile, () => {});
      res.end();
    });
  } catch (error) {
    try { fs.unlinkSync(tmpFile); } catch {}
    console.error('TTS stream error:', error.message);
    if (!res.headersSent) res.status(500).json({ error: error.message });
    else res.end();
  }
});

// TTS - 非流式 (兼容)
app.post('/api/tts', async (req, res) => {
  const { text } = req.body;
  if (!text || !text.trim()) {
    return res.status(400).json({ error: 'text is required' });
  }

  const tmpFile = path.join(os.tmpdir(), `tts-${Date.now()}.mp3`);

  try {
    await new Promise((resolve, reject) => {
      execFile('edge-tts', [
        '--text', text.slice(0, 500),
        '--voice', TTS_VOICE,
        '--write-media', tmpFile
      ], { timeout: 15000 }, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });

    const audioData = fs.readFileSync(tmpFile);
    fs.unlinkSync(tmpFile);

    res.set('Content-Type', 'audio/mpeg');
    res.send(audioData);
  } catch (error) {
    try { fs.unlinkSync(tmpFile); } catch {}
    console.error('TTS error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`小龙虾语音助手已启动: http://localhost:${PORT}`);
  console.log(`OpenClaw Gateway: ${GATEWAY_URL}`);
  console.log(`TTS: edge-tts (${TTS_VOICE})`);
  console.log(`流式端点: POST /api/chat/stream, POST /api/tts/stream`);
});
