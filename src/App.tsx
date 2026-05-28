import React, { useState, useCallback, useEffect, useRef } from 'react'
import { StatusBar } from './components/StatusBar'
import { ChatPanel } from './components/ChatPanel'
import { ControlBar } from './components/ControlBar'
import { InputArea } from './components/InputArea'
import { LogPanel } from './components/LogPanel'
import { useWebSocket } from './hooks/useWebSocket'
import { useAudioCapture } from './hooks/useAudioCapture'
import { useTTSPlayer, handleTTSMessage } from './hooks/useTTSPlayer'
import { useSoundEffects } from './hooks/useSoundEffects'
import type { AppState, ChatMessage, LogEntry, ServerMessage } from './types'

let msgId = 0
const genId = () => String(++msgId)

export default function App() {
  const { connected, appState, stateText, send, onMessage } = useWebSocket()
  const { isCapturing, isVoiceActive, startCapture, stopCapture } = useAudioCapture(send)
  const ttsPlayer = useTTSPlayer(send)
  useSoundEffects(appState)

  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: genId(), role: 'system', content: '小龙虾语音助手就绪', timestamp: Date.now() },
    { id: genId(), role: 'system', content: '"开始"唤醒 → 说话+"说完了"发送 → "结束结束"退出', timestamp: Date.now() },
  ])
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logVisible, setLogVisible] = useState(false)
  const [partialText, setPartialText] = useState('')
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
        case 'error':
          addMessage('system', `错误: ${msg.message}`)
          addLog(`错误: ${msg.message}`, 'error')
          break
        case 'state_change':
          addLog(`状态: ${msg.state} - ${msg.text || ''}`)
          break
      }
    })
  }, [onMessage, addMessage, addLog, ttsPlayer])

  useEffect(() => {
    const shouldCapture = ['wake_listening', 'listening', 'recognizing'].includes(appState) && !ttsPlayer.isPlaying
    if (shouldCapture) {
      if (!isCapturing) startCapture().catch((e) => {
        addMessage('system', `麦克风错误: ${e instanceof Error ? e.message : '权限被拒绝'}`)
      })
    } else {
      if (isCapturing) stopCapture()
    }
  }, [appState, isCapturing, ttsPlayer.isPlaying, startCapture, stopCapture, addMessage])

  const handleStartWake = useCallback(() => {
    send({ type: 'command', action: 'start_wake' })
  }, [send])

  const handleStartConversation = useCallback(() => {
    send({ type: 'command', action: 'start_conversation' })
  }, [send])

  const handleStop = useCallback(() => {
    ttsPlayer.stop()
    send({ type: 'command', action: 'stop' })
  }, [send, ttsPlayer])

  const handleClear = useCallback(() => {
    send({ type: 'command', action: 'clear' })
    setMessages([{ id: genId(), role: 'system', content: '对话已清空', timestamp: Date.now() }])
  }, [send])

  const handleSendText = useCallback(
    (text: string) => {
      addMessage('user', text)
      send({ type: 'text_input', text })
    },
    [send, addMessage]
  )

  return (
    <div className="app-container">
      <div className="header">
        <h1>🦐 小龙虾语音助手</h1>
        <div className="subtitle">说"开始"唤醒 · 说"说完了"发送 · 说"结束结束"退出</div>
      </div>

      <StatusBar state={appState} text={stateText} connected={connected} />

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
