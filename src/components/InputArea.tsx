import React, { useState, useCallback, useEffect, useRef } from 'react'

interface Props {
  partialText: string
  onSend: (text: string) => void
  disabled: boolean
}

export const InputArea: React.FC<Props> = ({ partialText, onSend, disabled }) => {
  const [inputValue, setInputValue] = useState('')
  const [userEditing, setUserEditing] = useState(false)
  const prevPartialRef = useRef(partialText)

  useEffect(() => {
    if (partialText !== prevPartialRef.current) {
      prevPartialRef.current = partialText
      if (!userEditing && partialText) {
        setInputValue(partialText)
      }
    }
  }, [partialText, userEditing])

  const handleSend = useCallback(() => {
    const text = inputValue.trim()
    if (!text) return
    onSend(text)
    setInputValue('')
    setUserEditing(false)
  }, [inputValue, onSend])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleSend()
    },
    [handleSend]
  )

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setUserEditing(true)
    setInputValue(e.target.value)
  }, [])

  const handleBlur = useCallback(() => {
    if (!inputValue.trim()) setUserEditing(false)
  }, [inputValue])

  return (
    <div className="input-area">
      <input
        type="text"
        value={inputValue}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        placeholder="输入文字或语音..."
        disabled={disabled}
        className={!userEditing && partialText ? 'partial' : ''}
      />
      <button className="btn btn-send" onClick={handleSend} disabled={disabled}>
        <svg viewBox="0 0 24 24">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
        </svg>
      </button>
    </div>
  )
}
