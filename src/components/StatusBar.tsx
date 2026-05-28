import React from 'react'
import type { AppState } from '../types'

interface Props {
  state: AppState
  text: string
  connected: boolean
}

const STATE_LABELS: Record<AppState, string> = {
  idle: '就绪',
  wake_listening: '等待唤醒',
  listening: '聆听中',
  recognizing: '识别中',
  thinking: 'AI 思考中',
  playing: '播报中',
}

export const StatusBar: React.FC<Props> = ({ state, text, connected }) => {
  return (
    <div className="status-bar">
      <div className={`status-dot ${state}`} />
      <span className="status-text">
        {connected ? (text || STATE_LABELS[state]) : '未连接后端'}
      </span>
      {!connected && <span className="conn-badge">离线</span>}
    </div>
  )
}
