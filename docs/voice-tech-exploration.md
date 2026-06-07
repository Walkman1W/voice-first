# 语音交互技术探讨：唤醒、打断、命令触发与声纹识别

> 目标：识别准确、命令触发快、执行响应快、对播放内容有掌控感

---

## 1. 关键词唤醒 (Keyword Wake Word Detection)

### 1.1 技术路线对比

| 方案 | 延迟 | 准确率 | 资源占用 | 代表项目 |
|------|------|--------|----------|----------|
| 传统信号处理 (MFCC + HMM) | <50ms | 中 | 极低 | Pocketsphinx |
| 小模型 CNN/CRNN | <100ms | 高 | 低 | Mycroft Precise, openWakeWord |
| RNN/GRU 流式模型 | <150ms | 高 | 中 | Picovoice Porcupine |
| Transformer 蒸馏模型 | <200ms | 很高 | 中 | Whisper tiny + fine-tune |

### 1.2 推荐开源方案

**openWakeWord** (Python, Apache 2.0)
- 基于 Google Speech Commands 数据集训练
- 支持自定义唤醒词，几百条样本即可微调
- ONNX 推理，树莓派可跑，延迟 ~80ms
- GitHub: `dscripka/openWakeWord`

**Picovoice Porcupine**
- 跨平台 SDK（浏览器 WASM 也支持）
- 免费版支持有限唤醒词，企业版可完全自定义
- 延迟极低 <50ms，误唤醒率 < 1次/12小时

**Mycroft Precise**
- GRU 模型，极轻量
- 社区活跃，有中文唤醒词训练经验

### 1.3 浏览器端唤醒的挑战

Web Speech API 本身没有"唤醒"概念——它要么在听，要么没在听。当前项目的做法（持续监听 + 字符匹配唤醒词）其实是"软唤醒"。真正的低功耗唤醒需要：

- **Web Audio API + AudioWorklet**: 直接处理音频流
- **ONNX Runtime Web / TFLite WASM**: 在浏览器跑轻量唤醒模型
- **Porcupine Web SDK**: 现成方案，WASM 打包

---

## 2. 语音打断 / Turn Detection (Barge-in)

### 2.1 LiveKit 的 Turn Detection 模型

LiveKit 开源了其语音 agent 框架中的 **End-of-Turn (EOT) / Turn Detection** 组件：

- **项目**: `livekit/agents` (Python framework)
- **模型**: 一个轻量分类模型，判断用户是否结束说话
- **输入特征**: 静音时长、语音能量、语速变化、语义完整性
- **延迟**: ~200-300ms 判定
- **核心思路**: 不只靠 VAD 静音检测（那太慢，需等 1-2s），而是结合语义信号提前判断

### 2.2 打断技术的几种路线

#### 路线 A：VAD (Voice Activity Detection) 驱动

```
用户开始说话 → VAD 检测到语音 → 立即停止 TTS 播放 → 开始新一轮 STT
```

- **Silero VAD**: ONNX 模型，8KB 大小，延迟 <30ms，精度极高
- **WebRTC VAD**: 浏览器原生集成，C++ 移植
- 缺点：容易被背景噪音误触发、无法区分"嗯嗯"等反馈和真正打断

#### 路线 B：语义级打断检测

```
用户说话 → STT 实时转写 → 语义模型判断意图 → 决定是否打断
```

- 结合 ASR 的 partial result 判断
- LiveKit 的做法：用一个小分类器判断 partial text 是否是"打断意图"
- 更智能但延迟更高（+300-500ms）

#### 路线 C：混合策略（推荐）

```
Layer 1: 能量检测 → 降低 TTS 音量（<20ms）
Layer 2: VAD 确认 → 暂停 TTS（<100ms）
Layer 3: 语义确认 → 停止 TTS 并开始处理新输入（<500ms）
```

### 2.3 对播放内容的掌控感

关键技术点：
- **流式 TTS + 分句播放**: 不要等全部合成完再播，按句子粒度播放
- **播放队列可取消**: 随时中断未播放的句子
- **播放进度回报**: 前端知道当前播放到哪句话
- **语速/跳过控制**: "跳过"/"快进"/"重复" 等语音命令

---

## 3. 命令触发：从字符匹配到智能匹配

### 3.1 方案光谱（延迟从低到高）

```
字符精确匹配 → 模糊匹配/编辑距离 → 正则模板 → 向量语义匹配 → LLM 工具调用
   <1ms           <5ms              <5ms        10-50ms          200-2000ms
```

### 3.2 字符/模糊匹配（最快，<5ms）

```javascript
// 精确匹配
if (text === "暂停") pause();

// 编辑距离容错（处理 STT 误差）
if (levenshtein(text, "暂停") <= 1) pause();

// 拼音匹配（处理同音字）
if (pinyin(text) === "zanting") pause();
```

适用：固定命令集小（<50个），需要极速响应

### 3.3 向量语义匹配（快速，10-50ms）

**核心思路**：把命令意图预编码为向量，用户输入实时编码后做余弦相似度匹配

```
预计算阶段：
  "暂停播放" → embed → [0.2, 0.8, ...]
  "停止说话" → embed → [0.3, 0.7, ...]
  "安静"    → embed → [0.25, 0.75, ...]
  → 这三个都映射到 action: "pause_tts"

运行时：
  用户说 "别说了" → embed → [0.28, 0.72, ...] → cosine_sim → 最近邻 = "pause_tts"
```

**推荐模型**：
- **BGE-small-zh** (BAAI): 中文语义向量，512维，ONNX 推理 ~10ms
- **text2vec-base-chinese**: 哈工大出品，适合短文本
- **all-MiniLM-L6-v2**: 多语言，极轻量，ONNX 可浏览器跑

**优势**：
- 不怕 STT 错别字（"停一下"和"听一下"语义不同，向量距离大）
- 天然支持同义表达（"闭嘴"≈"别说了"≈"安静"）
- 可设阈值，低于阈值就不触发（避免误触发）

**实现方案**：
- 服务端: `sentence-transformers` + numpy，预热后 <10ms
- 浏览器端: `@xenova/transformers` (Transformers.js)，ONNX 推理

### 3.4 LLM 工具匹配（最智能，200-2000ms）

```
用户: "把刚才那段话再说一遍，但是慢一点"
→ LLM function calling:
  {tool: "replay_last", params: {speed: 0.7}}
```

**适用场景**：
- 复杂命令（带参数、上下文依赖）
- 模糊表达需要推理
- 命令集动态变化

**加速策略**：
- 用小模型（Qwen2.5-1.5B / Phi-3-mini）做本地 tool matching
- 预定义 tool schema，限制输出格式（减少 token 生成量）
- Speculative decoding / 提前终止
- 只在向量匹配置信度低时才 fallback 到 LLM

### 3.5 混合分层架构（推荐）

```
用户语音 → STT partial result
  ↓
Layer 1: 精确匹配（<1ms）→ 命中？→ 执行
  ↓ 未命中
Layer 2: 向量匹配（~20ms）→ 相似度 > 0.85？→ 执行
  ↓ 未命中或置信度低
Layer 3: LLM 工具调用（~500ms）→ 执行
```

这种分层设计保证了：
- 高频简单命令极速响应
- 同义表达和口语变体被向量层捕获
- 复杂/新命令由 LLM 兜底

---

## 4. 声纹识别 (Speaker Verification / Identification)

### 4.1 技术现状

声纹识别已经非常成熟，主要用于：
- **说话人验证 (Speaker Verification)**: 1:1，确认是否是某个人
- **说话人识别 (Speaker Identification)**: 1:N，在已知说话人中识别是谁
- **说话人分离 (Speaker Diarization)**: 多人对话中区分谁在说话

### 4.2 开源方案

**SpeechBrain** (PyTorch, Apache 2.0)
- ECAPA-TDNN 模型，EER < 1%（极高精度）
- 支持声纹注册、验证、识别全流程
- 预训练模型基于 VoxCeleb 数据集

**Wespeaker** (WeNet 团队)
- 工业级声纹方案，支持 ResNet/ECAPA-TDNN
- 提供 ONNX 导出，适合部署
- 中文场景训练，对中文说话人效果更好

**Resemblyzer**
- 轻量 Python 库，基于 GE2E (Google) 模型
- 256 维 embedding，注册只需 5-10s 语音
- 适合快速原型验证

**3D-Speaker** (阿里达摩院)
- 最新的大规模中文声纹数据集 + 预训练模型
- 适合中文场景，性能领先

### 4.3 应用场景

```
场景 1：多用户识别
  声纹识别 → 用户 A → 加载 A 的偏好/命令集/对话历史

场景 2：安全命令保护
  "删除所有文件" → 声纹验证 → 确认是管理员 → 执行

场景 3：个性化响应
  声纹识别 → 用户 B → TTS 使用 B 偏好的语音/语速/风格
```

### 4.4 实际部署考量

- **注册**: 需要 3-10 秒清晰语音，生成 256/512 维 embedding 存储
- **验证延迟**: 提取 embedding ~100ms + 比对 <1ms
- **准确率**: 安静环境 EER <2%，噪声环境需要降噪前处理
- **活体检测**: 防录音回放攻击，需要额外模型

---

## 5. 端到端方案参考

### 5.1 LiveKit Agents Framework

```
音频流 → STT (Deepgram/Whisper) → LLM Agent → TTS (ElevenLabs/Edge)
              ↑                                      ↓
         Turn Detection ←───── VAD ←──────── 音频播放状态
```

- 完整的语音 agent 框架
- 内建打断、turn detection、并发控制
- Python SDK，可自定义每个环节

### 5.2 Picovoice 全家桶

```
Porcupine (唤醒) → Cheetah/Leopard (STT) → Rhino (NLU/意图) → [你的逻辑]
     <50ms              实时流式               <100ms
```

- 全部边缘推理，无需网络
- Rhino 是关键：把语音直接映射到结构化意图，不需要 LLM
- 适合嵌入式/离线场景

### 5.3 Rasa + 语音前端

```
语音 → ASR → Rasa NLU (意图 + 实体提取) → Rasa Core (对话管理) → Action
```

- Rasa 的意图识别模型轻量且可自定义
- 支持 few-shot 训练新意图
- 适合命令集较大但模式固定的场景

---

## 6. 针对本项目的建议方案

### 6.1 短期可落地（1-2周）

| 层 | 技术 | 用途 |
|----|------|------|
| 唤醒 | Porcupine Web SDK 或 openWakeWord + AudioWorklet | 替代当前字符匹配唤醒 |
| 打断 | Silero VAD (ONNX Web) + 播放队列控制 | 用户说话时立即暂停播放 |
| 快速命令 | 精确匹配 + 拼音容错 | "暂停"/"继续"/"重复" 等 |
| TTS 掌控 | 分句播放 + 可取消队列 | 随时中断、跳过、重复 |

### 6.2 中期增强（1-2月）

| 层 | 技术 | 用途 |
|----|------|------|
| 语义命令 | BGE-small-zh 向量匹配 | 支持自然语言命令变体 |
| 声纹 | Wespeaker/SpeechBrain | 多用户识别、安全验证 |
| 智能打断 | 语义级打断判断 | 区分"嗯嗯"反馈和真正打断 |

### 6.3 长期愿景

| 层 | 技术 | 用途 |
|----|------|------|
| 端到端 | 本地小 LLM tool calling | 任意命令理解 |
| 个性化 | 声纹 + 用户画像 | 不同人不同响应策略 |
| 多模态 | 唇语/手势辅助 | 噪声环境下提升准确率 |

---

## 7. 关键指标参考

| 能力 | 目标延迟 | 业界水平 |
|------|----------|----------|
| 唤醒检测 | <100ms | Porcupine: 30-50ms |
| VAD 打断 | <100ms | Silero: 30ms |
| STT 首字 | <300ms | Whisper Streaming: 200ms |
| 快速命令触发 | <50ms | 字符匹配: <1ms |
| 向量命令匹配 | <50ms | BGE-small: 10-20ms |
| LLM 命令理解 | <1000ms | Qwen2.5-1.5B: 300-500ms |
| 声纹验证 | <200ms | ECAPA-TDNN: 100-150ms |

---

## 8. 参考资源

- LiveKit Agents: `github.com/livekit/agents`
- openWakeWord: `github.com/dscripka/openWakeWord`
- Silero VAD: `github.com/snakers4/silero-vad`
- Picovoice: `picovoice.ai`
- SpeechBrain: `github.com/speechbrain/speechbrain`
- Wespeaker: `github.com/wenet-e2e/wespeaker`
- 3D-Speaker: `github.com/alibaba-damo-academy/3D-Speaker`
- BGE Embedding: `github.com/FlagOpen/FlagEmbedding`
- Transformers.js: `github.com/xenova/transformers.js`
- Rasa: `github.com/RasaHQ/rasa`
