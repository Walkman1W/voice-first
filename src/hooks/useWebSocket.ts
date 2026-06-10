import { useRef, useCallback, useEffect, useState } from 'react'
import type { ServerMessage, ClientMessage, AppState } from '../types'
import { appConfig } from '../config'

export interface WebSocketHook {
  connected: boolean
  appState: AppState
  stateText: string
  send: (msg: ClientMessage) => void
  onMessage: (handler: (msg: ServerMessage) => void) => () => void
}

export function useWebSocket(): WebSocketHook {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [appState, setAppState] = useState<AppState>('idle')
  const [stateText, setStateText] = useState('未连接')
  const handlersRef = useRef<Array<(msg: ServerMessage) => void>>([])
  const reconnectTimer = useRef<number | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(appConfig.wsUrl)

    ws.onopen = () => {
      setConnected(true)
      setStateText('已连接')
    }

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data)
        if (msg.type === 'state_change' && msg.state) {
          setAppState(msg.state)
          if (msg.text) setStateText(msg.text)
        }
        for (const handler of handlersRef.current) {
          handler(msg)
        }
      } catch (e) {
        console.error('WS message parse error:', e)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      setAppState('idle')
      setStateText('连接断开，重连中...')
      wsRef.current = null
      reconnectTimer.current = window.setTimeout(connect, 2000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((msg: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const onMessage = useCallback((handler: (msg: ServerMessage) => void) => {
    handlersRef.current.push(handler)
    return () => {
      handlersRef.current = handlersRef.current.filter((h) => h !== handler)
    }
  }, [])

  return { connected, appState, stateText, send, onMessage }
}
