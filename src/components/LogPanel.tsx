import React, { useRef, useEffect } from 'react'
import type { LogEntry } from '../types'

interface Props {
  logs: LogEntry[]
  visible: boolean
}

export const LogPanel: React.FC<Props> = ({ logs, visible }) => {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (visible && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, visible])

  return (
    <div className={`log-panel ${visible ? 'visible' : ''}`}>
      {logs.map((log) => (
        <div key={log.id} className={`log-entry l${log.level[0]}`}>
          <span className="lt">{log.time}</span>
          <span className="ls">[{log.state}]</span>
          <span className="lm">{log.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
