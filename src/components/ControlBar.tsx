import React from 'react'
import type { AppState } from '../types'

interface Props {
  state: AppState
  isCapturing: boolean
  onStartWake: () => void
  onStartConversation: () => void
  onStop: () => void
  onClear: () => void
  onToggleLog: () => void
  logVisible: boolean
}

export const ControlBar: React.FC<Props> = ({
  state,
  isCapturing,
  onStartWake,
  onStartConversation,
  onStop,
  onClear,
  onToggleLog,
  logVisible,
}) => {
  const isWakeActive = state === 'wake_listening'
  const isConvActive = ['listening', 'recognizing', 'thinking', 'playing'].includes(state)

  return (
    <div className="controls">
      <button
        className={`control-btn ${isWakeActive ? 'active' : ''}`}
        onClick={isWakeActive ? onStop : onStartWake}
      >
        {isWakeActive ? '停止监听' : '启动唤醒'}
      </button>
      <button
        className={`control-btn ${isConvActive ? 'active' : ''}`}
        onClick={isConvActive ? onStop : onStartConversation}
      >
        {isConvActive ? '退出对话' : '直接对话'}
      </button>
      <button className="control-btn" onClick={onClear}>
        清空
      </button>
      <button className={`control-btn ${logVisible ? 'active' : ''}`} onClick={onToggleLog}>
        日志
      </button>
    </div>
  )
}
