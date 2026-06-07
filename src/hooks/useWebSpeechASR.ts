import { useRef, useCallback, useState } from 'react'
import { appConfig } from '../config'
import type { ClientMessage } from '../types'

export interface WebSpeechASRHook {
  isListening: boolean
  startListening: () => void
  stopListening: () => void
  forceFinalize: () => void
  resumeListening: () => void
}

interface SpeechRecognitionEvent {
  resultIndex: number
  results: SpeechRecognitionResultList
}

interface SpeechRecognitionErrorEvent {
  error: string
  message?: string
}

type SpeechRecognitionInstance = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognitionInstance
    webkitSpeechRecognition: new () => SpeechRecognitionInstance
  }
}

export function useWebSpeechASR(
  send: (msg: ClientMessage) => void,
  onEvent?: (message: string) => void
): WebSpeechASRHook {
  const [isListening, setIsListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const shouldRestartRef = useRef(false)

  const startListening = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      onEvent?.('Web Speech API 不可用，请使用 Chrome/Edge 浏览器')
      return
    }

    if (recognitionRef.current) return

    const recognition = new SpeechRecognition()
    recognition.lang = appConfig.speechLanguage
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setIsListening(true)
      onEvent?.('Web Speech ASR: 开始监听')
    }

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        const text = result[0].transcript.trim()
        if (!text) continue

        if (result.isFinal) {
          send({ type: 'asr_result', text, is_final: true })
        } else {
          send({ type: 'asr_result', text, is_final: false })
        }
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'no-speech' || event.error === 'aborted') {
        return
      }
      onEvent?.(`Web Speech ASR 错误: ${event.error}`)
      if (event.error === 'not-allowed') {
        shouldRestartRef.current = false
        recognitionRef.current = null
        setIsListening(false)
      }
    }

    recognition.onend = () => {
      if (shouldRestartRef.current && recognitionRef.current === recognition) {
        try {
          recognition.start()
        } catch {
          setIsListening(false)
          recognitionRef.current = null
          shouldRestartRef.current = false
        }
      } else {
        if (recognitionRef.current === recognition) {
          recognitionRef.current = null
        }
        setIsListening(false)
      }
    }

    shouldRestartRef.current = true
    recognitionRef.current = recognition

    try {
      recognition.start()
    } catch {
      onEvent?.('Web Speech ASR: 启动失败')
      recognitionRef.current = null
      shouldRestartRef.current = false
      setIsListening(false)
    }
  }, [send, onEvent])

  const stopListening = useCallback(() => {
    shouldRestartRef.current = false
    if (recognitionRef.current) {
      recognitionRef.current.abort()
      recognitionRef.current = null
    }
    setIsListening(false)
    onEvent?.('Web Speech ASR: 停止监听')
  }, [onEvent])

  const forceFinalize = useCallback(() => {
    shouldRestartRef.current = false
    if (recognitionRef.current) {
      recognitionRef.current.stop()
    }
  }, [])

  const resumeListening = useCallback(() => {
    if (!recognitionRef.current) {
      startListening()
      return
    }
    shouldRestartRef.current = true
    try {
      recognitionRef.current.start()
    } catch {
      // already running, ignore
    }
  }, [startListening])

  return { isListening, startListening, stopListening, forceFinalize, resumeListening }
}
