import { useRef, useCallback, useState } from 'react'
import type { ServerMessage, ClientMessage } from '../types'

export interface TTSPlayerHook {
  isPlaying: boolean
  play: (audioBase64: string, format: string) => Promise<void>
  stop: () => void
}

export function useTTSPlayer(send: (msg: ClientMessage) => void): TTSPlayerHook {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const resolveRef = useRef<(() => void) | null>(null)

  const play = useCallback(async (audioBase64: string, format: string) => {
    stop()

    const mimeType = format === 'mp3' ? 'audio/mpeg' : `audio/${format}`
    const binaryStr = atob(audioBase64)
    const bytes = new Uint8Array(binaryStr.length)
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i)
    }
    const blob = new Blob([bytes], { type: mimeType })
    const url = URL.createObjectURL(blob)

    return new Promise<void>((resolve) => {
      const audio = new Audio(url)
      audioRef.current = audio
      resolveRef.current = resolve
      setIsPlaying(true)

      audio.onended = () => {
        cleanup(url)
        send({ type: 'tts_playback_done' })
        resolve()
      }
      audio.onerror = () => {
        cleanup(url)
        send({ type: 'tts_playback_done' })
        resolve()
      }
      audio.play().catch(() => {
        cleanup(url)
        send({ type: 'tts_playback_done' })
        resolve()
      })
    })
  }, [send])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    if (resolveRef.current) {
      resolveRef.current()
      resolveRef.current = null
    }
    setIsPlaying(false)
  }, [])

  function cleanup(url: string) {
    URL.revokeObjectURL(url)
    audioRef.current = null
    resolveRef.current = null
    setIsPlaying(false)
  }

  return { isPlaying, play, stop }
}

export function handleTTSMessage(
  msg: ServerMessage,
  player: TTSPlayerHook
): boolean {
  if (msg.type === 'tts_audio' && msg.data && msg.format) {
    player.play(msg.data, msg.format)
    return true
  }
  return false
}
