import React, { useState, useCallback } from 'react'

interface Props {
  partialText: string
  onSend: (text: string) => void
  disabled: boolean
}

export const InputArea: React.FC<Props> = ({ partialText, onSend, disabled }) => {
  const [inputValue, setInputValue] = useState('')

  const displayValue = partialText || inputValue

  const handleSend = useCallback(() => {
    const text = inputValue.trim()
    if (!text) return
    onSend(text)
    setInputValue('')
  }, [inputValue, onSend])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleSend()
    },
    [handleSend]
  )

  return (
    <div className="input-area">
      <input
        type="text"
        value={displayValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入文字或语音..."
        disabled={disabled}
        className={partialText ? 'partial' : ''}
      />
      <button className="btn btn-send" onClick={handleSend} disabled={disabled}>
        <svg viewBox="0 0 24 24">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
        </svg>
      </button>
    </div>
  )
}
