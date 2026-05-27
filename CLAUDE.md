# 小龙虾语音助手 (Crayfish Voice Assistant)

## 项目概述
一个基于网页的 AI 语音助手，支持语音唤醒、语音输入、AI 对话、语音播报。

## 技术栈
- **前端**: 原生 HTML/CSS/JS 单页应用
- **后端**: Node.js + Express
- **语音识别**: Web Speech API (浏览器原生)
- **AI 对话**: OpenClaw Gateway (本地 OpenAI 兼容 API)
- **语音合成**: mimo-v2.5-tts (通过 OpenClaw gateway)，降级到浏览器 TTS

## 架构

```
用户语音 → Web Speech API (STT, 实时显示在输入框) → 后端 /api/chat → OpenClaw Gateway → AI回复
                                                                                          ↓
用户听到 ← 浏览器播放音频 ← 后端 /api/tts ← edge-tts (微软免费TTS)
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
task01/
├── CLAUDE.md          # 本文件
├── package.json       # 依赖
├── server.js          # Express 后端
└── public/
    └── index.html     # 前端 SPA
```

## 注意事项

- Web Speech API 需要 HTTPS 或 localhost 才能使用
- 建议使用 Chrome/Edge 浏览器，兼容性最好
- 语音唤醒模式下浏览器会持续访问麦克风
