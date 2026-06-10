import { useRef, useCallback, useState } from 'react'
import { appConfig } from '../config'
import type { ClientMessage } from '../types'

export interface VolcanoASRHook {
  isConnected: boolean
  isSessionActive: boolean
  startSession: () => void
  endSession: () => void
  feedAudio: (pcm16: Int16Array) => void
}

interface VolcanoResponse {
  type?: string
  connect_id?: string
  error?: string
  payload_msg?: {
    result?: {
      text?: string
      utterances?: Array<{
        text: string
        definite: boolean
        start_time: number
        end_time: number
      }>
    }
  }
  header?: {
    status_code?: number
    status_message?: string
    message_type?: string
  }
}

export function useVolcanoASR(
  send: (msg: ClientMessage) => void,
  onEvent?: (message: string) => void,
  onFatalError?: (reason: string) => void
): VolcanoASRHook {
  const [isConnected, setIsConnected] = useState(false)
  const [isSessionActive, setIsSessionActive] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const sessionActiveRef = useRef(false)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keepAliveTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioBufferRef = useRef<Int16Array[]>([])
  const configSentRef = useRef(false)
  const lastAudioTimeRef = useRef(0)

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (keepAliveTimerRef.current) {
      clearInterval(keepAliveTimerRef.current)
      keepAliveTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.onerror = null
      wsRef.current.onmessage = null
      wsRef.current.close()
      wsRef.current = null
    }
    configSentRef.current = false
    setIsConnected(false)
  }, [])

  const startKeepAlive = useCallback(() => {
    if (keepAliveTimerRef.current) clearInterval(keepAliveTimerRef.current)
    const SILENCE_FRAME = new Int16Array(1600) // 100ms of silence at 16kHz
    keepAliveTimerRef.current = setInterval(() => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN || !configSentRef.current) return
      const elapsed = Date.now() - lastAudioTimeRef.current
      if (elapsed > 5000) {
        ws.send(SILENCE_FRAME.buffer)
      }
    }, 5000)
  }, [])

  const sendStartFrame = useCallback((ws: WebSocket) => {
    const startPayload = {
      user: {
        uid: appConfig.volcanoAsrUid,
      },
      audio: {
        format: 'pcm',
        codec: 'raw',
        rate: 16000,
        bits: 16,
        channel: 1,
        language: 'zh-CN',
      },
      request: {
        model_name: 'bigmodel',
        enable_itn: true,
        enable_punc: true,
        result_type: 'single',
        show_utterances: true,
      },
    }
    ws.send(JSON.stringify(startPayload))
    configSentRef.current = true
    onEvent?.('火山 ASR: 已发送配置帧')
  }, [onEvent])

  const connectRef = useRef<() => void>(() => {})

  const handleMessage = useCallback((data: string | ArrayBuffer) => {
    if (data instanceof ArrayBuffer) return

    try {
      const msg: VolcanoResponse = JSON.parse(data as string)

      if (msg.type === 'connected') {
        onEvent?.(`火山 ASR: 代理已连接 (${msg.connect_id})`)
        if (wsRef.current) {
          sendStartFrame(wsRef.current)
          startKeepAlive()
          lastAudioTimeRef.current = Date.now()
        }
        return
      }

      if (msg.error) {
        const errorStr = typeof msg.error === 'string' ? msg.error : JSON.stringify(msg.error)
        const isFatal = /quota exceeded|insufficient balance|account.*disabled/i.test(errorStr)
        if (isFatal) {
          onEvent?.(`火山 ASR 致命错误: ${errorStr}`)
          sessionActiveRef.current = false
          setIsSessionActive(false)
          cleanup()
          onFatalError?.(errorStr)
          return
        }
        const isTimeout = errorStr.includes('Timeout')
        if (isTimeout) {
          onEvent?.('火山 ASR: 会话超时，自动重连...')
          if (sessionActiveRef.current) {
            cleanup()
            setTimeout(() => { if (sessionActiveRef.current) connectRef.current() }, 500)
          }
        } else {
          onEvent?.(`火山 ASR 错误: ${errorStr}`)
        }
        return
      }

      // 非零状态码
      if (msg.header?.status_code && msg.header.status_code !== 0) {
        onEvent?.(`火山 ASR 错误: ${msg.header.status_message || msg.header.status_code}`)
        return
      }

      const result = msg.payload_msg?.result
      if (!result) return

      const utterances = result.utterances
      if (utterances && utterances.length > 0) {
        const lastUtterance = utterances[utterances.length - 1]
        const text = lastUtterance.text || result.text || ''
        const isFinal = lastUtterance.definite

        if (text) {
          if (isFinal) {
            send({ type: 'asr_result', text, is_final: true })
          } else {
            send({ type: 'asr_result', text, is_final: false })
          }
        }
      } else if (result.text) {
        send({ type: 'asr_result', text: result.text, is_final: false })
      }
    } catch {
      onEvent?.('火山 ASR: 解析响应失败')
    }
  }, [send, onEvent, onFatalError, sendStartFrame, startKeepAlive, cleanup])

  const connect = useCallback(() => {
    cleanup()

    // 连接本地后端 ASR 代理（后端携带 header 连接火山引擎）
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = import.meta.env.VITE_WS_PORT
      ? `${window.location.hostname}:${import.meta.env.VITE_WS_PORT}`
      : window.location.host
    const proxyUrl = `${wsProtocol}//${wsHost}/ws/asr`

    onEvent?.(`火山 ASR: 连接代理 ${proxyUrl}`)

    const ws = new WebSocket(proxyUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      onEvent?.('火山 ASR: 代理 WebSocket 已连接')
    }

    ws.onmessage = (event) => {
      handleMessage(event.data)
    }

    ws.onclose = (event) => {
      setIsConnected(false)
      configSentRef.current = false
      onEvent?.(`火山 ASR: 连接关闭 (${event.code})`)
      if (sessionActiveRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          if (sessionActiveRef.current) connect()
        }, 3000)
      }
    }

    ws.onerror = () => {
      onEvent?.('火山 ASR: 连接错误')
    }
  }, [cleanup, onEvent, handleMessage])
  connectRef.current = connect

  const startSession = useCallback(() => {
    sessionActiveRef.current = true
    setIsSessionActive(true)
    audioBufferRef.current = []
    connect()
  }, [connect])

  const endSession = useCallback(() => {
    sessionActiveRef.current = false
    setIsSessionActive(false)
    audioBufferRef.current = []

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ signal: 'end' }))
    }

    cleanup()
  }, [cleanup])

  const feedAudio = useCallback((pcm16: Int16Array) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !configSentRef.current) {
      audioBufferRef.current.push(pcm16)
      return
    }

    while (audioBufferRef.current.length > 0) {
      const buffered = audioBufferRef.current.shift()!
      wsRef.current.send(buffered.buffer)
    }

    wsRef.current.send(pcm16.buffer)
    lastAudioTimeRef.current = Date.now()
  }, [])

  return { isConnected, isSessionActive, startSession, endSession, feedAudio }
}
