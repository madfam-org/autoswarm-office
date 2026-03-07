'use client';

import { useEffect } from 'react';

interface MediaControlsProps {
  audioEnabled: boolean;
  videoEnabled: boolean;
  onToggleAudio: () => void;
  onToggleVideo: () => void;
  visible: boolean;
}

/**
 * Mute (M) and camera (V) toggle buttons.
 * Positioned at top-left below the video bubbles.
 */
export function MediaControls({
  audioEnabled,
  videoEnabled,
  onToggleAudio,
  onToggleVideo,
  visible,
}: MediaControlsProps) {
  // Keyboard shortcuts: M for mute, V for camera
  useEffect(() => {
    if (!visible) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if typing in an input
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      if (e.key === 'm' || e.key === 'M') {
        onToggleAudio();
      }
      if (e.key === 'v' || e.key === 'V') {
        onToggleVideo();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [visible, onToggleAudio, onToggleVideo]);

  if (!visible) return null;

  return (
    <div className="absolute top-4 left-4 z-video flex gap-2">
      <button
        onClick={onToggleAudio}
        className={`rounded px-2 py-1 text-xs font-mono transition-colors ${
          audioEnabled
            ? 'bg-slate-700/80 text-green-400 hover:bg-slate-600'
            : 'bg-red-900/80 text-red-300 hover:bg-red-800'
        }`}
        title={audioEnabled ? 'Mute (M)' : 'Unmute (M)'}
        aria-label={audioEnabled ? 'Mute microphone' : 'Unmute microphone'}
      >
        {audioEnabled ? 'MIC ON' : 'MIC OFF'}
      </button>

      <button
        onClick={onToggleVideo}
        className={`rounded px-2 py-1 text-xs font-mono transition-colors ${
          videoEnabled
            ? 'bg-slate-700/80 text-green-400 hover:bg-slate-600'
            : 'bg-red-900/80 text-red-300 hover:bg-red-800'
        }`}
        title={videoEnabled ? 'Camera Off (V)' : 'Camera On (V)'}
        aria-label={videoEnabled ? 'Turn camera off' : 'Turn camera on'}
      >
        {videoEnabled ? 'CAM ON' : 'CAM OFF'}
      </button>
    </div>
  );
}
