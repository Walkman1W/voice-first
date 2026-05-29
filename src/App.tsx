import React, { useState, useCallback, useEffect, useRef } from 'react'
import { StatusBar } from './components/StatusBar'
import { ChatPanel } from './components/ChatPanel'
import { ControlBar } from './components/ControlBar'
import { InputArea } from './components/InputArea'
import { LogPanel } from './components/LogPanel'
import { useWebSocket } from './hooks/useWebSocket'
import { useAudioCapture } from './hooks/useAudioCapture'
import { useWebSpeechASR } from './hooks/useWebSpeechASR'
import { useTTSPlayer, handleTTSMessage } from './hooks/useTTSPlayer'
import { playSoundCue, useSoundEffects } from './hooks/useSoundEffects'
import type { AppState, ASRConfig, ChatMessage, LogEntry, ServerMessage } from './types'

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
  const registeredRef = useRef(false)

  const appStateRef = useRef<AppState>(appState)
  appStateRef.current = appState

  const addMessage = useCallback((role: ChatMessage['role'], content: string) => {
    setMessages((prev) => [...prev, { id: genId(), role, content, timestamp: Date.now() }])
  }, [])

  const addLog = useCallback((message: string, level: LogEntry['level'] = 'info') => {
    const time = new Date().toTimeString().slice(0, 8)
    setLogs((prev) => {
      const next = [...prev, { id: genId(), time, state: appStateRef.current, message, level }]
      return next.length > 80 ? next.slice(-80) : next
    })
  }, [])

  const { isCapturing, isVoiceActive, startCapture, stopCapture } = useAudioCapture(
    send,
    inputDeviceId || undefined,
    (message) => addLog(message),
    asrConfig.mode === 'client'
  )
  const { isListening, startListening, stopListening } = useWebSpeechASR(
    send,
    (message) => addLog(message)
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
    if (registeredRef.current) return
    registeredRef.current = true

    onMessage((msg: ServerMessage) => {
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
      }
    })
  }, [onMessage, addMessage, addLog, ttsPlayer])

  useEffect(() => {
    const shouldCapture = connected && ['wake_listening', 'listening', 'recognizing', 'playing'].includes(appState)

    if (asrConfig.mode === 'client') {
      if (shouldCapture) {
        if (!isCapturing) startCapture().catch((e) => {
          addMessage('system', `VAD 启动失败: ${e instanceof Error ? e.message : '未知错误'}`)
        })
        if (!isListening) startListening()
      } else {
        if (isCapturing) stopCapture()
        if (isListening) stopListening()
      }
    } else {
      if (isListening) stopListening()
      if (shouldCapture) {
        if (!isCapturing) startCapture().catch((e) => {
          addMessage('system', `麦克风错误: ${e instanceof Error ? e.message : '权限被拒绝'}`)
        })
      } else {
        if (isCapturing) stopCapture()
      }
    }
  }, [connected, appState, asrConfig.mode, isCapturing, isListening, startCapture, stopCapture, startListening, stopListening, addMessage])

  const resumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
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
      }, 2000)
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
      </div>

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

      <InputArea
        partialText={partialText}
        onSend={handleSendText}
        disabled={!connected}
      />

      <LogPanel logs={logs} visible={logVisible} />
    </div>
  )
}
