import { useRef, useCallback, useState, useEffect } from 'react'
import { MicVAD } from '@ricky0123/vad-web'
import { appConfig } from '../config'
import type { ClientMessage } from '../types'

let micPermissionGranted = false

export function preRequestMicrophone() {
  if (micPermissionGranted) return
  navigator.mediaDevices?.getUserMedia({ audio: true }).then((stream) => {
    micPermissionGranted = true
    stream.getTracks().forEach((t) => t.stop())
  }).catch(() => {})
}

export interface AudioCaptureHook {
  isCapturing: boolean
  isVoiceActive: boolean
  startCapture: () => Promise<void>
  stopCapture: () => void
}

export function useAudioCapture(
  send: (msg: ClientMessage) => void,
  inputDeviceId?: string,
  onEvent?: (message: string) => void,
  vadOnly?: boolean,
  onVoiceEnd?: () => void,
  onVoiceStart?: () => void,
  onAudioFrame?: (pcm16: Int16Array) => void
): AudioCaptureHook {
  const [isCapturing, setIsCapturing] = useState(false)
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const vadRef = useRef<MicVAD | null>(null)
  const startingRef = useRef(false)
  const voiceActiveRef = useRef(false)
  const onAudioFrameRef = useRef(onAudioFrame)
  onAudioFrameRef.current = onAudioFrame

  useEffect(() => {
    preRequestMicrophone()
  }, [])

  const startCapture = useCallback(async () => {
    if (vadRef.current || startingRef.current) return
    startingRef.current = true

    try {
      const vad = await MicVAD.new({
        model: appConfig.vadModel,
        baseAssetPath: appConfig.vadAssetPath,
        onnxWASMBasePath: appConfig.vadAssetPath,
        ortConfig: (ort) => {
          ort.env.wasm.numThreads = 1
          ort.env.wasm.wasmPaths = appConfig.vadAssetPath
        },
        startOnLoad: true,
        positiveSpeechThreshold: appConfig.vadPositiveThreshold,
        negativeSpeechThreshold: appConfig.vadNegativeThreshold,
        minSpeechMs: appConfig.vadMinSpeechMs,
        redemptionMs: appConfig.vadRedemptionMs,
        ...(inputDeviceId ? {
          getStream: () => navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: inputDeviceId }, channelCount: 1 },
          }),
        } : {}),
        onFrameProcessed: (_probabilities: { isSpeech: number }, frame: Float32Array) => {
          if (onAudioFrameRef.current) {
            const pcm16 = float32ToPCM16(frame)
            onAudioFrameRef.current(pcm16)
          }
        },
        onSpeechStart: () => {
          voiceActiveRef.current = true
          setIsVoiceActive(true)
          onEvent?.('Silero VAD: voice_start')
          onVoiceStart?.()
          send({ type: 'voice_start' })
        },
        onSpeechEnd: (audio: Float32Array) => {
          voiceActiveRef.current = false
          setIsVoiceActive(false)
          onEvent?.('Silero VAD: voice_end')
          onVoiceEnd?.()

          if (!vadOnly) {
            const pcm16 = float32ToPCM16(audio)
            const b64 = arrayBufferToBase64(pcm16.buffer)
            send({ type: 'audio_data', data: b64 })
          }
          window.setTimeout(() => send({ type: 'voice_end' }), 0)
        },
        onVADMisfire: () => {
          if (voiceActiveRef.current) {
            voiceActiveRef.current = false
            setIsVoiceActive(false)
          }
        },
      })

      if (!startingRef.current) {
        vad.destroy()
        return
      }
      vadRef.current = vad
      startingRef.current = false
      setIsCapturing(true)
      onEvent?.(`Silero VAD 输入轨已启动${vadOnly ? ' (仅检测)' : ''}`)
    } catch (error) {
      startingRef.current = false
      const msg = error instanceof Error ? error.message : '麦克风权限被拒绝或设备不可用'
      throw new Error(msg)
    }
  }, [send, inputDeviceId, onEvent, vadOnly, onVoiceEnd, onVoiceStart])

  const stopCapture = useCallback(() => {
    startingRef.current = false
    if (voiceActiveRef.current) {
      send({ type: 'voice_end' })
    }
    if (vadRef.current) {
      vadRef.current.destroy()
      vadRef.current = null
    }
    voiceActiveRef.current = false
    setIsCapturing(false)
    setIsVoiceActive(false)
    onEvent?.('Silero VAD 输入轨已停止')
  }, [send, onEvent])

  return { isCapturing, isVoiceActive, startCapture, stopCapture }
}

function float32ToPCM16(float32: Float32Array): Int16Array {
  const pcm16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return pcm16
}

function arrayBufferToBase64(buffer: ArrayBufferLike): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}
