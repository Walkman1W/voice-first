import { useRef, useCallback, useEffect } from 'react'
import type { AppState } from '../types'

let audioCtx: AudioContext | null = null

function getAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
  if (audioCtx.state === 'suspended') audioCtx.resume()
  return audioCtx
}

function beep(freq: number, duration: number, startTime: number) {
  const ctx = getAudioCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(0.15, startTime)
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

function soundTriple() {
  const ctx = getAudioCtx()
  const t = ctx.currentTime
  beep(880, 0.09, t)
  beep(660, 0.09, t + 0.11)
  beep(440, 0.12, t + 0.22)
}

function playTransitionSound(from: AppState, to: AppState) {
  if (from === 'idle' && to === 'wake_listening') { soundTriple(); return }
  if (to === 'idle' || (to === 'wake_listening' && from !== 'idle')) { soundTriple(); return }

  if (from === 'wake_listening' && to === 'listening') { soundDouble(); return }
  if (from === 'recognizing' && to === 'thinking') { soundDouble(); return }

  if (from === 'listening' && to === 'recognizing') { soundSingle(); return }
  if (from === 'playing' && to === 'listening') { soundSingle(); return }
}

export function useSoundEffects(appState: AppState) {
  const prevStateRef = useRef<AppState>(appState)

  useEffect(() => {
    const prev = prevStateRef.current
    if (prev !== appState) {
      playTransitionSound(prev, appState)
      prevStateRef.current = appState
    }
  }, [appState])
}
