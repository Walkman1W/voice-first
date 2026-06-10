# 小龙虾语音助手 (Crayfish Voice Assistant)

## 项目概述
一个基于网页的 AI 语音助手，支持语音唤醒、语音输入、AI 对话、语音播报。

## 技术栈
- **前端**: React + TypeScript + Vite (src/ 目录)
- **后端**: Python FastAPI + WebSocket (backend/ 目录)
- **VAD**: Silero VAD (@ricky0123/vad-web) - 浏览器端语音活动检测
- **语音识别**: 火山引擎豆包大模型 ASR (WebSocket 直连) / Web Speech API (降级)
- **AI 对话**: OpenClaw Gateway (本地 OpenAI 兼容 API)
- **语音合成**: edge-tts (微软免费 TTS)，后端生成音频回传前端

## 架构

```
用户语音 → 浏览器麦克风 + Silero VAD (检测说话)
                ↓
        ┌───────────────────────────────────┐
        │ ASR (二选一，配置切换)               │
        │  优先: 火山引擎豆包 WebSocket 直连    │
        │  备选: Web Speech API (浏览器原生)   │
        └───────────────────────────────────┘
                ↓ 识别文字
        浏览器 WebSocket → 本地后端 (Python FastAPI)
                ↓
        后端: 关键词判断 / LLM (OpenClaw Gateway) / TTS (edge-tts)
                ↓ 音频 base64
        浏览器 WebSocket ← 后端回传 TTS 音频
                ↓
        浏览器播放音频 (VAD 控制暂停/恢复)
```

## OpenClaw Gateway 配置

- 地址: `http://127.0.0.1:18789`
- 认证: Bearer token (`OPENCLAW_GATEWAY_TOKEN` 环境变量)
- 端点: `POST /v1/chat/completions`
- Model 字段: `openclaw/default` (路由到默认 agent)

**已启用**: `gateway.http.endpoints.chatCompletions.enabled = true`

## TTS 配置

使用 edge-tts (Microsoft Edge TTS)，免费无需 API Key。
- 默认语音: `zh-CN-XiaoxiaoNeural`
- 可通过环境变量 `TTS_VOICE` 更换
- 备选语音: `zh-CN-YunxiNeural`(男声), `zh-CN-XiaoyiNeural`

DashScope 备用 (账户欠费暂不可用):
- API Key: `sk-acf0af9ed7f4483db57af0dc68628c36`
- Model: `qwen3-tts-instruct-flash`

## ASR 配置

### 火山引擎豆包大模型 ASR (推荐)

浏览器直连火山引擎 WebSocket，低延迟实时识别。

配置环境变量 (`.env` 文件):
```bash
VITE_ASR_ENGINE=volcano
VITE_VOLCANO_ASR_APP_ID=你的应用ID
VITE_VOLCANO_ASR_TOKEN=你的访问令牌
VITE_VOLCANO_ASR_CLUSTER=volcengine_streaming_common
```

获取凭证: 火山引擎控制台 → 语音技术 → 创建应用 → 获取 App ID 和 Token

### Web Speech API (降级方案)

浏览器原生 API，无需配置，但依赖 Google 服务器。
```bash
VITE_ASR_ENGINE=webspeech
```

## 运行

```bash
# 安装依赖
npm install

# 系统依赖 (TTS)
pip3 install --break-system-packages edge-tts

# 启动服务
npm start
# 访问 http://localhost:3000
```

## 功能模块

1. **语音唤醒** - 持续监听唤醒词("开始"/"小龙虾")，识别内容实时显示在输入框
2. **语音输入** - 唤醒后持续监听用户语音，实时显示识别文字（interim结果灰色，final结果白色）
3. **AI 对话** - 调用 OpenClaw gateway 获取 AI 回复
4. **语音播报** - 使用 edge-tts 将回复转为语音，播报结束后自动继续监听

## 文件结构

```
voice-first/
├── CLAUDE.md              # 本文件
├── package.json           # 依赖
├── .env.example           # 环境变量模板
├── index.html             # Vite 入口 HTML
├── server.js              # 旧版 Express 后端 (legacy)
├── backend/
│   ├── main.py            # FastAPI 主后端 + WebSocket
│   ├── state_machine.py   # 状态机
│   ├── command_parser.py  # 关键词解析
│   ├── keyword_dispatcher.py
│   ├── text_segmenter.py  # TTS 分句
│   └── engines/
│       ├── base.py        # 引擎抽象基类
│       ├── asr_edge.py    # 客户端 ASR (接收前端结果)
│       ├── asr_volcano.py # 火山引擎 ASR (预留)
│       ├── asr_vosk.py    # Vosk 本地 ASR
│       ├── tts_edge.py    # edge-tts 引擎
│       └── llm_openclaw.py # OpenClaw LLM 引擎
├── src/
│   ├── App.tsx            # 主应用组件
│   ├── config.ts          # 应用配置 (含火山 ASR 配置)
│   ├── types.ts           # TypeScript 类型定义
│   ├── components/        # UI 组件
│   └── hooks/
│       ├── useWebSocket.ts     # 后端 WebSocket 通信
│       ├── useAudioCapture.ts  # 麦克风采集 + Silero VAD
│       ├── useVolcanoASR.ts    # 火山引擎 ASR WebSocket 客户端
│       ├── useWebSpeechASR.ts  # Web Speech API ASR (降级方案)
│       ├── useTTSPlayer.ts     # TTS 音频播放队列
│       └── useSoundEffects.ts  # 音效
└── public/
    └── index.html         # 旧版 SPA (legacy)
```

## 注意事项

- Web Speech API 需要 HTTPS 或 localhost 才能使用
- 建议使用 Chrome/Edge 浏览器，兼容性最好
- 语音唤醒模式下浏览器会持续访问麦克风
