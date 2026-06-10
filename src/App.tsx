import React, { useState, useCallback, useEffect, useRef } from 'react'
import { StatusBar } from './components/StatusBar'
import { ChatPanel } from './components/ChatPanel'
import { ControlBar } from './components/ControlBar'
import { PlaybackBar } from './components/PlaybackBar'
import { InputArea } from './components/InputArea'
import { LogPanel } from './components/LogPanel'
import { useWebSocket } from './hooks/useWebSocket'
import { useAudioCapture, preRequestMicrophone } from './hooks/useAudioCapture'

preRequestMicrophone()
import { useWebSpeechASR } from './hooks/useWebSpeechASR'
import { useVolcanoASR } from './hooks/useVolcanoASR'
import { useTTSPlayer, handleTTSMessage } from './hooks/useTTSPlayer'
import { playSoundCue, useSoundEffects } from './hooks/useSoundEffects'
import { appConfig } from './config'
import type { AppState, ASRConfig, ChatMessage, LogEntry, ServerMessage, TimingData } from './types'
import type { ASREngineType } from './config'

let msgId = 0
const genId = () => String(++msgId)

export default function App() {
  const { connected, appState, stateText, send, onMessage } = useWebSocket()
  const [asrConfig, setAsrConfig] = useState<ASRConfig>({ mode: 'server', engine: 'unknown' })
  const [inputDevices, setInputDevices] = useState<MediaDeviceInfo[]>([])
  const [outputDevices, setOutputDevices] = useState<MediaDeviceInfo[]>([])
  const [inputDeviceId, setInputDeviceId] = useState('')
  const [outputDeviceId, setOutputDeviceId] = useState('')
  const ttsPlayer = useTTSPlayer(send, outputDeviceId)

  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: genId(), role: 'system', content: '小龙虾语音助手就绪', timestamp: Date.now() },
    { id: genId(), role: 'system', content: '"开始"唤醒 → 说话+"说完了"发送 → "结束结束"退出', timestamp: Date.now() },
  ])
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logVisible, setLogVisible] = useState(false)
  const [partialText, setPartialText] = useState('')
  const [trackState, setTrackState] = useState({ thinking: false, playing: false })
  const [timing, setTiming] = useState<TimingData>({})

  const appStateRef = useRef<AppState>(appState)
  appStateRef.current = appState

  const addMessage = useCallback((role: ChatMessage['role'], content: string) => {
    setMessages((prev) => [...prev, { id: genId(), role, content, timestamp: Date.now() }])
  }, [])

  const addLog = useCallback((message: string, level: LogEntry['level'] = 'info') => {
    const time = new Date().toTimeString().slice(0, 8)
    setLogs((prev) => {
      const next = [...prev, { id: genId(), time, state: appStateRef.current, message, level }]
      return next.length > appConfig.maxLogEntries ? next.slice(-appConfig.maxLogEntries) : next
    })
  }, [])

  const voiceGateRef = useRef(false)

  const { isListening, startListening, stopListening, forceFinalize, resumeListening } = useWebSpeechASR(
    send,
    (message) => addLog(message),
    voiceGateRef
  )

  const [asrEngine, setAsrEngine] = useState<ASREngineType>(appConfig.asrEngine)
  const useVolcanoEngine = asrEngine === 'volcano'

  const handleVolcanoFatalError = useCallback((reason: string) => {
    addMessage('system', `火山 ASR 不可用: ${reason}，已自动切换 Web Speech API`)
    addLog(`火山 ASR 致命错误，自动降级: ${reason}`, 'warn')
    setAsrEngine('webspeech')
  }, [addMessage, addLog])

  const volcanoASR = useVolcanoASR(send, (message) => addLog(message), handleVolcanoFatalError)

  const onAudioFrame = useCallback((pcm16: Int16Array) => {
    if (useVolcanoEngine) {
      volcanoASR.feedAudio(pcm16)
    }
  }, [useVolcanoEngine, volcanoASR.feedAudio])

  const { isCapturing, isVoiceActive, startCapture, stopCapture } = useAudioCapture(
    send,
    inputDeviceId || undefined,
    (message) => addLog(message),
    asrConfig.mode === 'client',
    useVolcanoEngine ? undefined : undefined,
    useVolcanoEngine ? undefined : undefined,
    useVolcanoEngine ? onAudioFrame : undefined
  )
  useSoundEffects(appState, isVoiceActive)

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    const devices = await navigator.mediaDevices.enumerateDevices()
    setInputDevices(devices.filter((d) => d.kind === 'audioinput'))
    setOutputDevices(devices.filter((d) => d.kind === 'audiooutput'))
  }, [])

  useEffect(() => {
    refreshDevices().catch(() => undefined)
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices)
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices)
  }, [refreshDevices])

  useEffect(() => {
    return onMessage((msg: ServerMessage) => {
      switch (msg.type) {
        case 'asr_partial':
          setPartialText(msg.text || '')
          break
        case 'asr_final':
          setPartialText(msg.text || '')
          addLog(`识别: ${msg.text}`, 'cmd')
          break
        case 'user_message':
          addMessage('user', msg.text || '')
          setPartialText('')
          setTiming({})
          addLog(`发送: ${msg.text}`, 'cmd')
          break
        case 'ai_reply':
          addMessage('assistant', msg.text || '')
          addLog(`AI: ${(msg.text || '').slice(0, 40)}`)
          break
        case 'tts_audio':
          handleTTSMessage(msg, ttsPlayer)
          break
        case 'tts_done':
          handleTTSMessage(msg, ttsPlayer)
          break
        case 'command_result':
          if (msg.action === 'clear') {
            setMessages([{ id: genId(), role: 'system', content: '对话已清空', timestamp: Date.now() }])
          }
          addLog(`命令: ${msg.action} ${msg.success ? '成功' : '失败'}`, 'cmd')
          break
        case 'vad_event':
          addLog(`${msg.text || msg.action || 'VAD 事件'}`, 'info')
          break
        case 'keyword':
          addLog(`关键词命中: ${msg.action} (${msg.text || ''})`, 'cmd')
          break
        case 'track_update':
          if (msg.track === 'thinking' || msg.track === 'playing') {
            setTrackState((prev) => ({ ...prev, [msg.track as 'thinking' | 'playing']: Boolean(msg.active) }))
          }
          if ((msg.text || '').includes('确认发送')) playSoundCue('send')
          addLog(`${msg.track || 'track'}: ${msg.text || ''}`)
          break
        case 'playback_control':
          if (msg.action === 'clear') ttsPlayer.clear()
          if (msg.action === 'stop_current') ttsPlayer.stopCurrent()
          if (msg.action === 'pause') ttsPlayer.pause()
          if (msg.action === 'resume') {
            ttsPlayer.resume()
            playSoundCue('resume')
          }
          addLog(`播放控制: ${msg.action}`, 'cmd')
          break
        case 'error':
          addMessage('system', `错误: ${msg.message}`)
          addLog(`错误: ${msg.message}`, 'error')
          break
        case 'state_change':
          addLog(`状态: ${msg.state} - ${msg.text || ''}`)
          break
        case 'asr_config':
          if (msg.mode && msg.engine) {
            setAsrConfig({ mode: msg.mode, engine: msg.engine })
            addLog(`ASR 引擎: ${msg.engine} (模式: ${msg.mode})`, 'info')
          }
          break
        case 'playback_status':
          addLog(`播放状态: ${msg.current_index !== undefined ? msg.current_index + 1 : 0}/${msg.total_segments || 0}`)
          break
        case 'timing':
          if (msg.stage === 'asr') {
            setTiming((prev) => ({ ...prev, asr: msg.elapsed }))
            addLog(`⏱ ASR: ${msg.elapsed}s`, 'cmd')
          } else if (msg.stage === 'agent') {
            setTiming((prev) => ({ ...prev, agent: msg.elapsed, agentFirstToken: msg.first_token }))
            addLog(`⏱ Agent: ${msg.elapsed}s (首token: ${msg.first_token}s)`, 'cmd')
          } else if (msg.stage === 'tts') {
            setTiming((prev) => ({ ...prev, tts: msg.elapsed }))
            addLog(`⏱ TTS: ${msg.elapsed}s`, 'cmd')
          } else if (msg.stage === 'intent') {
            setTiming((prev) => ({ ...prev, intent: msg.elapsed }))
            addLog(`⏱ 意图判断: ${msg.elapsed}s`, 'cmd')
          }
          break
        case 'intent_result':
          addLog(`意图: ${msg.intent} | ${msg.reason || ''} (${msg.text || ''})`, 'cmd')
          break
      }
    })
  }, [onMessage, addMessage, addLog, ttsPlayer])

  useEffect(() => {
    const shouldCapture = connected && ['wake_listening', 'listening', 'recognizing', 'playing'].includes(appState)

    if (useVolcanoEngine) {
      // 火山引擎模式：VAD 采集 + 火山 ASR WebSocket
      if (shouldCapture) {
        if (!isCapturing) startCapture().catch((e) => {
          addMessage('system', `VAD 启动失败: ${e instanceof Error ? e.message : '未知错误'}`)
        })
        if (!volcanoASR.isSessionActive) volcanoASR.startSession()
      } else {
        if (isCapturing) stopCapture()
        if (volcanoASR.isSessionActive) volcanoASR.endSession()
      }
      if (isListening) stopListening()
    } else {
      // Web Speech 模式：VAD 采集 + Web Speech API 持续运行
      if (shouldCapture) {
        if (!isCapturing) startCapture().catch((e) => {
          addMessage('system', `VAD 启动失败: ${e instanceof Error ? e.message : '未知错误'}`)
        })
        if (!isListening) startListening()
      } else {
        if (isCapturing) stopCapture()
        if (isListening) stopListening()
      }
      if (volcanoASR.isSessionActive) volcanoASR.endSession()
    }
  }, [connected, appState, isCapturing, isListening, startCapture, stopCapture, startListening, stopListening, addMessage, useVolcanoEngine, volcanoASR.isSessionActive, volcanoASR.startSession, volcanoASR.endSession])

  const resumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    voiceGateRef.current = isVoiceActive
    if (isVoiceActive) {
      if (resumeTimerRef.current) {
        clearTimeout(resumeTimerRef.current)
        resumeTimerRef.current = null
      }
      ttsPlayer.setSpeechBlocked(true)
    } else {
      resumeTimerRef.current = setTimeout(() => {
        ttsPlayer.setSpeechBlocked(false)
        resumeTimerRef.current = null
      }, appConfig.playbackResumeDelayMs)
    }
    return () => {
      if (resumeTimerRef.current) {
        clearTimeout(resumeTimerRef.current)
      }
    }
  }, [isVoiceActive, ttsPlayer.setSpeechBlocked])

  useEffect(() => {
    if (isCapturing) refreshDevices().catch(() => undefined)
  }, [isCapturing, refreshDevices])

  const handleStartWake = useCallback(() => {
    send({ type: 'command', action: 'start_wake' })
  }, [send])

  const handleStartConversation = useCallback(() => {
    send({ type: 'command', action: 'start_conversation' })
  }, [send])

  const handleStop = useCallback(() => {
    ttsPlayer.clear()
    send({ type: 'command', action: 'stop' })
  }, [send, ttsPlayer.clear])

  const handleClear = useCallback(() => {
    send({ type: 'command', action: 'clear' })
    setMessages([{ id: genId(), role: 'system', content: '对话已清空', timestamp: Date.now() }])
  }, [send])

  const handleSendText = useCallback(
    (text: string) => {
      send({ type: 'text_input', text })
    },
    [send]
  )

  return (
    <div className="app-container">
      <div className="header">
        <h1>🦐 小龙虾语音助手</h1>
        <div className="subtitle">说"开始"唤醒 · 说"说完了"发送 · 说"结束结束"退出</div>
      </div>

      <StatusBar state={appState} text={stateText} connected={connected} />

      <div className="device-bar">
        <label>
          <span>识别引擎</span>
          <select
            value={asrEngine}
            onChange={(e) => {
              const newEngine = e.target.value as ASREngineType
              if (newEngine === asrEngine) return
              if (useVolcanoEngine && volcanoASR.isSessionActive) volcanoASR.endSession()
              if (!useVolcanoEngine && isListening) stopListening()
              setAsrEngine(newEngine)
              addLog(`ASR 引擎切换: ${newEngine}`, 'cmd')
            }}
          >
            <option value="volcano">火山引擎</option>
            <option value="webspeech">Web Speech API</option>
          </select>
        </label>
        <label>
          <span>麦克风</span>
          <select
            value={inputDeviceId}
            onChange={(e) => {
              setInputDeviceId(e.target.value)
              if (isCapturing) stopCapture()
            }}
          >
            <option value="">默认输入</option>
            {inputDevices.map((device, index) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `麦克风 ${index + 1}`}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>输出</span>
          <select value={outputDeviceId} onChange={(e) => setOutputDeviceId(e.target.value)}>
            <option value="">默认输出</option>
            {outputDevices.map((device, index) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `扬声器 ${index + 1}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="track-strip">
        <span className={isCapturing ? 'on' : ''}>输入轨 {isCapturing ? '运行' : '停止'}</span>
        <span className={trackState.thinking ? 'on' : ''}>处理轨 {trackState.thinking ? '思考中' : '空闲'}</span>
        <span className={(ttsPlayer.isPlaying || ttsPlayer.queueLength > 0 || trackState.playing) ? 'on' : ''}>
          播放轨 {ttsPlayer.isPaused ? '暂停' : ttsPlayer.isPlaying ? '播放中' : ttsPlayer.queueLength > 0 ? `排队 ${ttsPlayer.queueLength}` : '空闲'}
        </span>
        <span className={useVolcanoEngine ? (volcanoASR.isConnected ? 'on' : '') : (isListening ? 'on' : '')}>
          ASR {useVolcanoEngine ? `火山${volcanoASR.isConnected ? ' 已连接' : ' 未连接'}` : `WebSpeech${isListening ? ' 监听中' : ''}`}
        </span>
      </div>

      {(timing.asr !== undefined || timing.agent !== undefined || timing.tts !== undefined) && (
        <div className="timing-bar">
          {timing.asr !== undefined && <span className="timing-tag asr">ASR {timing.asr}s</span>}
          {timing.intent !== undefined && <span className="timing-tag intent">意图 {timing.intent}s</span>}
          {timing.agent !== undefined && <span className="timing-tag agent">Agent {timing.agent}s</span>}
          {timing.agentFirstToken !== undefined && <span className="timing-tag agent-ft">首token {timing.agentFirstToken}s</span>}
          {timing.tts !== undefined && <span className="timing-tag tts">TTS {timing.tts}s</span>}
        </div>
      )}

      <div className={`visualizer ${isVoiceActive ? '' : 'hidden'}`}>
        <div className="bar" /><div className="bar" /><div className="bar" /><div className="bar" /><div className="bar" />
      </div>

      <ChatPanel messages={messages} />

      <ControlBar
        state={appState}
        isCapturing={isCapturing}
        onStartWake={handleStartWake}
        onStartConversation={handleStartConversation}
        onStop={handleStop}
        onClear={handleClear}
        onToggleLog={() => setLogVisible((v) => !v)}
        logVisible={logVisible}
      />

      <PlaybackBar
        player={ttsPlayer}
        onPlaybackCommand={(action) => {
          send({ type: 'playback_command', action })
          addLog(`播放控制(UI): ${action}`, 'cmd')
        }}
      />

      <InputArea
        partialText={partialText}
        onSend={handleSendText}
        disabled={!connected}
      />

      <LogPanel logs={logs} visible={logVisible} />
    </div>
  )
}
