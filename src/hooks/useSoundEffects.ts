import { useRef, useCallback, useEffect } from 'react'
import type { AppState } from '../types'

let audioCtx: AudioContext | null = null

function getAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
  if (audioCtx.state === 'suspended') audioCtx.resume()
  return audioCtx
}

function beep(freq: number, duration: number, startTime: number, volume = 0.15) {
  const ctx = getAudioCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(volume, startTime)
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration)
  osc.start(startTime)
  osc.stop(startTime + duration)
}

function soundSingle() {
  const ctx = getAudioCtx()
  beep(880, 0.12, ctx.currentTime)
}

function soundDouble() {
  const ctx = getAudioCtx()
  const t = ctx.currentTime
  beep(660, 0.1, t)
  beep(880, 0.12, t + 0.12)
}

function soundUp() {
  const ctx = getAudioCtx()
  const t = ctx.currentTime
  beep(880, 0.09, t)
  beep(1100, 0.09, t + 0.11)
  beep(1320, 0.12, t + 0.22)
}

function soundDown() {
  const ctx = getAudioCtx()
  const t = ctx.currentTime
  beep(880, 0.09, t)
  beep(660, 0.09, t + 0.11)
  beep(440, 0.12, t + 0.22)
}

function soundHeartbeat() {
  const ctx = getAudioCtx()
  beep(200, 0.08, ctx.currentTime, 0.03)
}

function playTransitionSound(from: AppState, to: AppState) {
  if (from === 'idle' && to === 'wake_listening') { soundUp(); return }
  if (to === 'idle' || (to === 'wake_listening' && from !== 'idle')) { soundDown(); return }

  if (from === 'wake_listening' && to === 'listening') { soundDouble(); return }
  if (from === 'recognizing' && to === 'thinking') { soundDouble(); return }

  if (from === 'listening' && to === 'recognizing') { soundSingle(); return }
  if (from === 'playing' && to === 'listening') { soundSingle(); return }
}

export function playSoundCue(cue: 'send' | 'resume') {
  if (cue === 'send') soundDouble()
  if (cue === 'resume') soundSingle()
}

export function useSoundEffects(appState: AppState, isVoiceActive: boolean) {
  const prevStateRef = useRef<AppState>(appState)
  const heartbeatTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const prev = prevStateRef.current
    if (prev !== appState) {
      playTransitionSound(prev, appState)
      prevStateRef.current = appState
    }
  }, [appState])

  useEffect(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current)
      heartbeatTimerRef.current = null
    }
    if (appState !== 'listening' || isVoiceActive) return

    heartbeatTimerRef.current = window.setInterval(soundHeartbeat, 4000)
    return () => {
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current)
        heartbeatTimerRef.current = null
      }
    }
  }, [appState, isVoiceActive])
}
