import React from 'react'
import type { TTSPlayerHook } from '../hooks/useTTSPlayer'

interface Props {
  player: TTSPlayerHook
  onPlaybackCommand?: (action: string) => void
}

export const PlaybackBar: React.FC<Props> = ({ player, onPlaybackCommand }) => {
  const { isPlaying, isPaused, currentIndex, totalSegments, currentText } = player
  const hasContent = totalSegments > 0

  const handlePrev = () => {
    player.prev()
    onPlaybackCommand?.('prev')
  }

  const handleNext = () => {
    player.next()
    onPlaybackCommand?.('next')
  }

  const handleTogglePlay = () => {
    if (isPlaying && !isPaused) {
      player.pause()
      onPlaybackCommand?.('pause')
    } else {
      player.resume()
      onPlaybackCommand?.('resume')
    }
  }

  const handleReplay = () => {
    player.replay()
    onPlaybackCommand?.('replay')
  }

  const displayIndex = currentIndex >= 0 ? currentIndex + 1 : 0
  const progress = totalSegments > 0 ? ((currentIndex + 1) / totalSegments) * 100 : 0
  const canPrev = currentIndex > 0
  const canNext = currentIndex < totalSegments - 1 && totalSegments > 0

  return (
    <div className="playback-bar">
      <div className="playback-progress">
        <div className="playback-progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <div className="playback-info">
        <span className="playback-counter">
          {hasContent ? `${displayIndex}/${totalSegments}` : '--/--'}
        </span>
        <span className="playback-text" title={currentText}>
          {currentText || (isPlaying ? '播放中...' : '等待语音回复')}
        </span>
      </div>

      <div className="playback-controls">
        <button
          className="playback-btn"
          onClick={handlePrev}
          disabled={!canPrev}
          title="上一句"
        >
          <svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>
        </button>

        <button
          className="playback-btn playback-btn-main"
          onClick={handleTogglePlay}
          disabled={!hasContent}
          title={isPlaying && !isPaused ? '暂停' : '播放'}
        >
          {isPlaying && !isPaused ? (
            <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          ) : (
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
          )}
        </button>

        <button
          className="playback-btn"
          onClick={handleNext}
          disabled={!canNext}
          title="下一句"
        >
          <svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>
        </button>

        <button
          className="playback-btn"
          onClick={handleReplay}
          disabled={currentIndex < 0}
          title="再说一遍"
        >
          <svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>
        </button>
      </div>
    </div>
  )
}
