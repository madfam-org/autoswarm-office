'use client';

import { useState, useRef, useCallback } from 'react';
import type { ProximityPeer } from './useProximityVideo';
import { logger } from '../lib/logger';

type RecordingState = 'idle' | 'recording' | 'processing';

interface UseRecordingOptions {
  localStream: MediaStream | null;
  peers: ProximityPeer[];
}

export function useRecording({ localStream, peers }: UseRecordingOptions) {
  const [state, setState] = useState<RecordingState>('idle');
  const [duration, setDuration] = useState(0);
  const [lastRecordingUrl, setLastRecordingUrl] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef(0);
  const mixedStreamRef = useRef<MediaStream | null>(null);

  const startRecording = useCallback(() => {
    if (!localStream || state !== 'idle') return;

    try {
      // Create AudioContext to mix local + remote audio
      const audioCtx = new AudioContext();
      const destination = audioCtx.createMediaStreamDestination();

      // Add local audio
      const localAudioTracks = localStream.getAudioTracks();
      if (localAudioTracks.length > 0) {
        const localSource = audioCtx.createMediaStreamSource(
          new MediaStream(localAudioTracks),
        );
        localSource.connect(destination);
      }

      // Add remote peer audio
      for (const peer of peers) {
        if (peer.stream) {
          const remoteTracks = peer.stream.getAudioTracks();
          if (remoteTracks.length > 0) {
            const remoteSource = audioCtx.createMediaStreamSource(
              new MediaStream(remoteTracks),
            );
            remoteSource.connect(destination);
          }
        }
      }

      // Combine mixed audio + local video into one stream
      const mixedTracks: MediaStreamTrack[] = [
        ...destination.stream.getAudioTracks(),
        ...localStream.getVideoTracks(),
      ];
      const mixedStream = new MediaStream(mixedTracks);
      mixedStreamRef.current = mixedStream;

      // Prefer webm with opus codec
      const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
        ? 'video/webm;codecs=vp9,opus'
        : MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')
          ? 'video/webm;codecs=vp8,opus'
          : 'video/webm';

      const recorder = new MediaRecorder(mixedStream, { mimeType });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      recorder.onstop = () => {
        setState('processing');
        const blob = new Blob(chunksRef.current, { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.download = `selva-recording-${timestamp}.webm`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // Keep the URL for meeting notes generation instead of revoking
        setLastRecordingUrl(url);
        chunksRef.current = [];
        mixedStreamRef.current = null;
        setState('idle');
        setDuration(0);
      };

      recorder.start(1000); // Collect data every second
      recorderRef.current = recorder;
      startTimeRef.current = Date.now();
      setState('recording');

      // Duration timer
      timerRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);
    } catch (err) {
      logger.warn('[useRecording] Failed to start recording:', err);
    }
  }, [localStream, peers, state]);

  const stopRecording = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop();
      recorderRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const formatDuration = useCallback((secs: number): string => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }, []);

  return {
    recordingState: state,
    duration,
    formattedDuration: formatDuration(duration),
    lastRecordingUrl,
    startRecording,
    stopRecording,
  };
}
