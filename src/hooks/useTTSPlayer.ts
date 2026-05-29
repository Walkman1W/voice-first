import { useRef, useCallback, useState } from 'react'
import type { ServerMessage, ClientMessage } from '../types'

export interface TTSPlayerHook {
  isPlaying: boolean
  isPaused: boolean
  queueLength: number
  enqueue: (audioBase64: string, format: string) => void
  pause: () => void
  resume: () => void
  stop: () => void
  clear: () => void
  setSpeechBlocked: (blocked: boolean) => void
}

interface QueueItem {
  audioBase64: string
  format: string
}

export function useTTSPlayer(send: (msg: ClientMessage) => void, outputDeviceId?: string): TTSPlayerHook {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [queueLength, setQueueLength] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const queueRef = useRef<QueueItem[]>([])
  const speechBlockedRef = useRef(false)
  const manualPausedRef = useRef(false)
  const outputDeviceIdRef = useRef(outputDeviceId)
  outputDeviceIdRef.current = outputDeviceId

  const cleanupAudio = useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = null
    audioRef.current = null
    setIsPlaying(false)
    setIsPaused(false)
  }, [])

  const playNext = useCallback(() => {
    if (audioRef.current || speechBlockedRef.current || manualPausedRef.current) return
    const next = queueRef.current.shift()
    setQueueLength(queueRef.current.length)
    if (!next) return

    const mimeType = next.format === 'mp3' ? 'audio/mpeg' : `audio/${next.format}`
    const binaryStr = atob(next.audioBase64)
    const bytes = new Uint8Array(binaryStr.length)
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i)
    }
    const blob = new Blob([bytes], { type: mimeType })
    const url = URL.createObjectURL(blob)
    urlRef.current = url

    const audio = new Audio(url)
    const sinkAudio = audio as HTMLAudioElement & { setSinkId?: (sinkId: string) => Promise<void> }
    audioRef.current = audio
    setIsPlaying(true)
    setIsPaused(false)

    const finish = () => {
      cleanupAudio()
      send({ type: 'tts_playback_done' })
      playNext()
    }

    audio.onended = finish
    audio.onerror = finish

    const start = () => audio.play().catch(finish)
    if (outputDeviceIdRef.current && sinkAudio.setSinkId) {
      sinkAudio.setSinkId(outputDeviceIdRef.current).then(start).catch(start)
    } else {
      start()
    }
  }, [cleanupAudio, send])

  const enqueue = useCallback((audioBase64: string, format: string) => {
    queueRef.current.push({ audioBase64, format })
    setQueueLength(queueRef.current.length)
    playNext()
  }, [playNext])

  const pause = useCallback(() => {
    manualPausedRef.current = true
    if (audioRef.current) {
      audioRef.current.pause()
      setIsPaused(true)
    }
  }, [])

  const resume = useCallback(() => {
    if (speechBlockedRef.current) return
    manualPausedRef.current = false
    if (audioRef.current) {
      audioRef.current.play().then(() => setIsPaused(false)).catch(() => undefined)
    } else {
      playNext()
    }
  }, [playNext])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
    }
    cleanupAudio()
  }, [cleanupAudio])

  const clear = useCallback(() => {
    queueRef.current = []
    setQueueLength(0)
    stop()
  }, [stop])

  const setSpeechBlocked = useCallback((blocked: boolean) => {
    speechBlockedRef.current = blocked
    if (blocked) {
      if (audioRef.current && !audioRef.current.paused) {
        audioRef.current.pause()
        setIsPaused(true)
      }
      return
    }
    if (audioRef.current && !manualPausedRef.current) {
      audioRef.current.play().then(() => setIsPaused(false)).catch(() => undefined)
    } else {
      playNext()
    }
  }, [playNext])

  return { isPlaying, isPaused, queueLength, enqueue, pause, resume, stop, clear, setSpeechBlocked }
}

export function handleTTSMessage(
  msg: ServerMessage,
  player: TTSPlayerHook
): boolean {
  if (msg.type === 'tts_audio' && msg.data && msg.format) {
    player.enqueue(msg.data, msg.format)
    return true
  }
  return false
}
