import { useRef, useCallback, useState } from 'react'
import type { ClientMessage } from '../types'

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
  vadOnly?: boolean
): AudioCaptureHook {
  const [isCapturing, setIsCapturing] = useState(false)
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const vadRef = useRef<any>(null)
  const voiceActiveRef = useRef(false)
  const failedRef = useRef(false)

  const startCapture = useCallback(async () => {
    if (vadRef.current || failedRef.current) return

    try {
      const { MicVAD } = await import('@ricky0123/vad-web')
      const vad = await MicVAD.new({
        model: 'v5',
        baseAssetPath: '/vad/',
        onnxWASMBasePath: '/vad/',
        startOnLoad: true,
        ...(inputDeviceId ? {
          getStream: () => navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: inputDeviceId }, channelCount: 1 },
          }),
        } : {}),
        onSpeechStart: () => {
          voiceActiveRef.current = true
          setIsVoiceActive(true)
          onEvent?.('Silero VAD: voice_start')
          if (!vadOnly) {
            send({ type: 'voice_start' })
          }
        },
        onSpeechEnd: (audio: Float32Array) => {
          voiceActiveRef.current = false
          setIsVoiceActive(false)
          onEvent?.('Silero VAD: voice_end')

          if (!vadOnly) {
            const pcm16 = float32ToPCM16(audio)
            const b64 = arrayBufferToBase64(pcm16.buffer)
            send({ type: 'audio_data', data: b64 })
            send({ type: 'voice_end' })
          }
        },
        onVADMisfire: () => {
          if (voiceActiveRef.current) {
            voiceActiveRef.current = false
            setIsVoiceActive(false)
          }
        },
      })

      vadRef.current = vad
      setIsCapturing(true)
      onEvent?.(`Silero VAD 输入轨已启动${vadOnly ? ' (仅检测)' : ''}`)
    } catch (error) {
      failedRef.current = true
      const msg = error instanceof Error ? error.message : '麦克风权限被拒绝或设备不可用'
      throw new Error(msg)
    }
  }, [send, inputDeviceId, onEvent, vadOnly])

  const stopCapture = useCallback(() => {
    if (voiceActiveRef.current && !vadOnly) {
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
  }, [send, onEvent, vadOnly])

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
