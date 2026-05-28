import { useRef, useCallback, useState } from 'react'
import type { ClientMessage } from '../types'

export interface AudioCaptureHook {
  isCapturing: boolean
  isVoiceActive: boolean
  startCapture: () => Promise<void>
  stopCapture: () => void
}

const SAMPLE_RATE = 16000
const FRAME_SIZE = 512
const VAD_THRESHOLD = 0.3
const SILENCE_FRAMES = 50

export function useAudioCapture(send: (msg: ClientMessage) => void): AudioCaptureHook {
  const [isCapturing, setIsCapturing] = useState(false)
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const contextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const workletRef = useRef<AudioWorkletNode | null>(null)
  const silenceCountRef = useRef(0)
  const voiceActiveRef = useRef(false)

  const startCapture = useCallback(async () => {
    if (isCapturing) return

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })

    const context = new AudioContext({ sampleRate: SAMPLE_RATE })
    const source = context.createMediaStreamSource(stream)

    await context.audioWorklet.addModule(createProcessorURL())
    const worklet = new AudioWorkletNode(context, 'pcm-processor', {
      processorOptions: { frameSize: FRAME_SIZE },
    })

    worklet.port.onmessage = (event) => {
      const pcmData: Float32Array = event.data
      processAudioFrame(pcmData)
    }

    source.connect(worklet)
    worklet.connect(context.destination)

    contextRef.current = context
    streamRef.current = stream
    workletRef.current = worklet
    silenceCountRef.current = 0
    voiceActiveRef.current = false
    setIsCapturing(true)
  }, [isCapturing, send])

  const processAudioFrame = useCallback((pcmFloat: Float32Array) => {
    const energy = computeEnergy(pcmFloat)
    const isVoice = energy > VAD_THRESHOLD

    if (isVoice) {
      silenceCountRef.current = 0
      if (!voiceActiveRef.current) {
        voiceActiveRef.current = true
        setIsVoiceActive(true)
        send({ type: 'voice_start' })
      }
      const pcm16 = float32ToPCM16(pcmFloat)
      const b64 = arrayBufferToBase64(pcm16.buffer)
      send({ type: 'audio_data', data: b64 })
    } else {
      if (voiceActiveRef.current) {
        const pcm16 = float32ToPCM16(pcmFloat)
        const b64 = arrayBufferToBase64(pcm16.buffer)
        send({ type: 'audio_data', data: b64 })

        silenceCountRef.current++
        if (silenceCountRef.current >= SILENCE_FRAMES) {
          voiceActiveRef.current = false
          setIsVoiceActive(false)
          send({ type: 'voice_end' })
        }
      }
    }
  }, [send])

  const stopCapture = useCallback(() => {
    if (voiceActiveRef.current) {
      send({ type: 'voice_end' })
    }
    workletRef.current?.disconnect()
    contextRef.current?.close()
    streamRef.current?.getTracks().forEach((t) => t.stop())
    workletRef.current = null
    contextRef.current = null
    streamRef.current = null
    voiceActiveRef.current = false
    setIsCapturing(false)
    setIsVoiceActive(false)
  }, [send])

  return { isCapturing, isVoiceActive, startCapture, stopCapture }
}

function computeEnergy(samples: Float32Array): number {
  let sum = 0
  for (let i = 0; i < samples.length; i++) {
    sum += samples[i] * samples[i]
  }
  return Math.sqrt(sum / samples.length) * 10
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

function createProcessorURL(): string {
  const code = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.frameSize = options.processorOptions?.frameSize || 512;
    this.buffer = new Float32Array(0);
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];
    const newBuffer = new Float32Array(this.buffer.length + channel.length);
    newBuffer.set(this.buffer);
    newBuffer.set(channel, this.buffer.length);
    this.buffer = newBuffer;
    while (this.buffer.length >= this.frameSize) {
      const frame = this.buffer.slice(0, this.frameSize);
      this.buffer = this.buffer.slice(this.frameSize);
      this.port.postMessage(frame);
    }
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
`
  const blob = new Blob([code], { type: 'application/javascript' })
  return URL.createObjectURL(blob)
}
