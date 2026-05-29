export type AppState = 'idle' | 'wake_listening' | 'listening' | 'recognizing' | 'thinking' | 'playing'

export type ASRMode = 'server' | 'client'

export interface ASRConfig {
  mode: ASRMode
  engine: string
}

export interface ServerMessage {
  type: 'state_change' | 'asr_partial' | 'asr_final' | 'ai_reply' | 'ai_reply_delta' | 'tts_audio' | 'tts_done' | 'command_result' | 'error' | 'user_message' | 'vad_event' | 'keyword' | 'track_update' | 'playback_control' | 'asr_config'
  state?: AppState
  text?: string
  data?: string
  format?: string
  action?: string
  track?: string
  active?: boolean
  success?: boolean
  message?: string
  mode?: ASRMode
  engine?: string
}

export interface ClientMessage {
  type: 'audio_data' | 'voice_start' | 'voice_end' | 'text_input' | 'command' | 'tts_playback_done' | 'asr_result'
  data?: string
  text?: string
  action?: string
  is_final?: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
}

export interface LogEntry {
  id: string
  time: string
  state: AppState
  message: string
  level: 'info' | 'warn' | 'error' | 'cmd'
}
