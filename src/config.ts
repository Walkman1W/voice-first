const numberEnv = (value: string | undefined, fallback: number) => {
  if (!value) return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const vadModel = (value: string | undefined): 'legacy' | 'v5' => (
  value === 'legacy' ? 'legacy' : 'v5'
)

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'

export type ASREngineType = 'volcano' | 'webspeech'

export const appConfig = {
  wsUrl: import.meta.env.VITE_WS_URL
    ? import.meta.env.VITE_WS_URL
    : import.meta.env.VITE_WS_PORT
      ? `${wsProtocol}//${window.location.hostname}:${import.meta.env.VITE_WS_PORT}/ws`
      : `${wsProtocol}//${window.location.host}/ws`,
  reconnectDelayMs: numberEnv(import.meta.env.VITE_RECONNECT_DELAY_MS, 2000),
  vadAssetPath: import.meta.env.VITE_VAD_ASSET_PATH || '/vad/',
  vadModel: vadModel(import.meta.env.VITE_VAD_MODEL),
  vadPositiveThreshold: numberEnv(import.meta.env.VITE_VAD_POSITIVE_THRESHOLD, 0.7),
  vadNegativeThreshold: numberEnv(import.meta.env.VITE_VAD_NEGATIVE_THRESHOLD, 0.3),
  vadMinSpeechMs: numberEnv(import.meta.env.VITE_VAD_MIN_SPEECH_MS, 250),
  vadRedemptionMs: numberEnv(import.meta.env.VITE_VAD_REDEMPTION_MS, 1000),
  speechLanguage: import.meta.env.VITE_SPEECH_LANGUAGE || 'zh-CN',
  playbackResumeDelayMs: numberEnv(import.meta.env.VITE_PLAYBACK_RESUME_DELAY_MS, 2000),
  maxLogEntries: numberEnv(import.meta.env.VITE_MAX_LOG_ENTRIES, 80),

  asrEngine: (import.meta.env.VITE_ASR_ENGINE || 'webspeech') as ASREngineType,
  volcanoAsrAppId: import.meta.env.VITE_VOLCANO_ASR_APP_ID || '',
  volcanoAsrToken: import.meta.env.VITE_VOLCANO_ASR_TOKEN || '',
  volcanoAsrWsUrl: import.meta.env.VITE_VOLCANO_ASR_WS_URL || 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel',
  volcanoAsrCluster: import.meta.env.VITE_VOLCANO_ASR_CLUSTER || 'volcengine_streaming_common',
  volcanoAsrUid: import.meta.env.VITE_VOLCANO_ASR_UID || 'crayfish-user',
}
