import { useRef, useCallback, useState } from 'react'
import type { ServerMessage, ClientMessage } from '../types'

export interface SegmentInfo {
  index: number
  text: string
}

export interface TTSPlayerHook {
  isPlaying: boolean
  isPaused: boolean
  queueLength: number
  currentIndex: number
  totalSegments: number
  currentText: string
  segments: SegmentInfo[]
  enqueue: (audioBase64: string, format: string, segmentIndex?: number, segmentText?: string) => void
  pause: () => void
  resume: () => void
  stop: () => void
  stopCurrent: () => void
  clear: () => void
  prev: () => void
  next: () => void
  replay: () => void
  jumpTo: (index: number) => void
  setSpeechBlocked: (blocked: boolean) => void
}

interface QueueItem {
  audioBase64: string
  format: string
  segmentIndex: number
  segmentText: string
}

export function useTTSPlayer(send: (msg: ClientMessage) => void, outputDeviceId?: string): TTSPlayerHook {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [queueLength, setQueueLength] = useState(0)
  const [currentIndex, setCurrentIndex] = useState(-1)
  const [totalSegments, setTotalSegments] = useState(0)
  const [currentText, setCurrentText] = useState('')
  const [segments, setSegments] = useState<SegmentInfo[]>([])

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const queueRef = useRef<QueueItem[]>([])
  const allSegmentsRef = useRef<QueueItem[]>([])
  const currentIndexRef = useRef(-1)
  const speechBlockedRef = useRef(false)
  const manualPausedRef = useRef(false)
  const outputDeviceIdRef = useRef(outputDeviceId)
  const sendRef = useRef(send)
  sendRef.current = send
  outputDeviceIdRef.current = outputDeviceId

  const syncState = useCallback(() => {
    setQueueLength(queueRef.current.length)
    setTotalSegments(allSegmentsRef.current.length)
    setSegments(allSegmentsRef.current.map((s) => ({ index: s.segmentIndex, text: s.segmentText })))
  }, [])

  const destroyAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.onended = null
      audioRef.current.onerror = null
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
  }, [])

  // Use a ref for the "advance" function to avoid stale closures
  const advanceRef = useRef<() => void>(() => {})

  const playItemDirect = useCallback((item: QueueItem) => {
    destroyAudio()

    const mimeType = item.format === 'mp3' ? 'audio/mpeg' : `audio/${item.format}`
    const binaryStr = atob(item.audioBase64)
    const bytes = new Uint8Array(binaryStr.length)
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i)
    }
    const blob = new Blob([bytes], { type: mimeType })
    const url = URL.createObjectURL(blob)
    urlRef.current = url

    const audio = new Audio(url)
    audioRef.current = audio

    currentIndexRef.current = item.segmentIndex
    setCurrentIndex(item.segmentIndex)
    setCurrentText(item.segmentText)
    setIsPlaying(true)
    setIsPaused(false)

    audio.onended = () => {
      destroyAudio()
      setIsPlaying(false)
      sendRef.current({ type: 'tts_playback_done' })
      advanceRef.current()
    }
    audio.onerror = () => {
      destroyAudio()
      setIsPlaying(false)
      sendRef.current({ type: 'tts_playback_done' })
      advanceRef.current()
    }

    const startPlay = () => audio.play().catch(() => {
      destroyAudio()
      setIsPlaying(false)
      advanceRef.current()
    })

    const sinkAudio = audio as HTMLAudioElement & { setSinkId?: (sinkId: string) => Promise<void> }
    if (outputDeviceIdRef.current && sinkAudio.setSinkId) {
      sinkAudio.setSinkId(outputDeviceIdRef.current).then(startPlay).catch(startPlay)
    } else {
      startPlay()
    }
  }, [destroyAudio])

  // advance: pull from queue and play next item
  advanceRef.current = () => {
    if (speechBlockedRef.current || manualPausedRef.current) return
    const next = queueRef.current.shift()
    setQueueLength(queueRef.current.length)
    if (!next) return
    playItemDirect(next)
  }

  const enqueue = useCallback((audioBase64: string, format: string, segmentIndex?: number, segmentText?: string) => {
    const idx = segmentIndex ?? allSegmentsRef.current.length
    const text = segmentText ?? ''
    const item: QueueItem = { audioBase64, format, segmentIndex: idx, segmentText: text }

    allSegmentsRef.current.push(item)
    queueRef.current.push(item)
    syncState()

    // If nothing is currently playing, start
    if (!audioRef.current && !speechBlockedRef.current && !manualPausedRef.current) {
      const toPlay = queueRef.current.shift()
      setQueueLength(queueRef.current.length)
      if (toPlay) playItemDirect(toPlay)
    }
  }, [syncState, playItemDirect])

  const pause = useCallback(() => {
    manualPausedRef.current = true
    if (audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause()
      setIsPaused(true)
    }
  }, [])

  const resume = useCallback(() => {
    if (speechBlockedRef.current) return
    manualPausedRef.current = false
    setIsPaused(false)
    if (audioRef.current) {
      audioRef.current.play().catch(() => undefined)
    } else {
      advanceRef.current()
    }
  }, [])

  const stop = useCallback(() => {
    destroyAudio()
    setIsPlaying(false)
    setIsPaused(false)
  }, [destroyAudio])

  const stopCurrent = useCallback(() => {
    queueRef.current = []
    setQueueLength(0)
    destroyAudio()
    setIsPlaying(false)
    setIsPaused(false)
  }, [destroyAudio])

  const clear = useCallback(() => {
    queueRef.current = []
    allSegmentsRef.current = []
    currentIndexRef.current = -1
    destroyAudio()
    setIsPlaying(false)
    setIsPaused(false)
    setQueueLength(0)
    setTotalSegments(0)
    setCurrentIndex(-1)
    setCurrentText('')
    setSegments([])
  }, [destroyAudio])

  const jumpTo = useCallback((index: number) => {
    const target = allSegmentsRef.current[index]
    if (!target) return
    // Clear pending queue so we don't auto-advance to old items
    queueRef.current = []
    setQueueLength(0)
    manualPausedRef.current = false
    playItemDirect(target)
  }, [playItemDirect])

  const prev = useCallback(() => {
    const cur = currentIndexRef.current
    if (cur <= 0) return
    jumpTo(cur - 1)
  }, [jumpTo])

  const next = useCallback(() => {
    const cur = currentIndexRef.current
    const max = allSegmentsRef.current.length - 1
    if (cur >= max) return
    jumpTo(cur + 1)
  }, [jumpTo])

  const replay = useCallback(() => {
    const cur = currentIndexRef.current
    if (cur < 0) return
    jumpTo(cur)
  }, [jumpTo])

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
    } else if (!manualPausedRef.current) {
      advanceRef.current()
    }
  }, [])

  return {
    isPlaying, isPaused, queueLength,
    currentIndex, totalSegments, currentText, segments,
    enqueue, pause, resume, stop, stopCurrent, clear,
    prev, next, replay, jumpTo,
    setSpeechBlocked,
  }
}

export function handleTTSMessage(
  msg: ServerMessage,
  player: TTSPlayerHook
): boolean {
  if (msg.type === 'tts_audio' && msg.data && msg.format) {
    player.enqueue(msg.data, msg.format, msg.segment_index, msg.segment_text)
    return true
  }
  return false
}
