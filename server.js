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

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// AI 对话 - OpenClaw Gateway
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

// TTS - edge-tts (免费, 高质量微软语音)
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
});
