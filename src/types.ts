export type AppState = 'idle' | 'wake_listening' | 'listening' | 'recognizing' | 'thinking' | 'playing'

export interface ServerMessage {
  type: 'state_change' | 'asr_partial' | 'asr_final' | 'ai_reply' | 'tts_audio' | 'tts_done' | 'command_result' | 'error' | 'user_message'
  state?: AppState
  text?: string
  data?: string
  format?: string
  action?: string
  success?: boolean
  message?: string
}

export interface ClientMessage {
  type: 'audio_data' | 'voice_start' | 'voice_end' | 'text_input' | 'command' | 'tts_playback_done'
  data?: string
  text?: string
  action?: string
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
