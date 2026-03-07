'use client';

import { useRef, useEffect, useState } from 'react';
import type { ProximityPeer } from '@/hooks/useProximityVideo';

interface VideoOverlayProps {
  peers: ProximityPeer[];
  localStream: MediaStream | null;
}

/**
 * Renders circular video bubbles for proximity video peers.
 * Positioned as an overlay above the Phaser canvas.
 * Each peer shows a 64px circular video element.
 */
export function VideoOverlay({ peers, localStream }: VideoOverlayProps) {
  const activePeers = peers.filter((p) => p.stream);
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const prevPeerIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    const currentIds = new Set(activePeers.map((p) => p.sessionId));
    // Detect peers that left
    prevPeerIds.current.forEach((id) => {
      if (!currentIds.has(id)) {
        setLeaving((prev) => new Set(prev).add(id));
        setTimeout(() => {
          setLeaving((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
        }, 200);
      }
    });
    prevPeerIds.current = currentIds;
  }, [activePeers]);

  if (activePeers.length === 0 && !localStream && leaving.size === 0) return null;

  return (
    <div className="pointer-events-none absolute top-16 left-4 z-video flex flex-col gap-2">
      {/* Local video preview (small) */}
      {localStream && (
        <div className="relative animate-pop-in">
          <VideoBubble stream={localStream} muted label="You" size={48} />
        </div>
      )}

      {/* Remote peer videos */}
      {activePeers.map((peer) => (
        <div key={peer.sessionId} className="relative animate-pop-in">
          <VideoBubble
            stream={peer.stream!}
            label={peer.sessionId.slice(0, 6)}
            size={64}
          />
        </div>
      ))}
    </div>
  );
}

interface VideoBubbleProps {
  stream: MediaStream;
  muted?: boolean;
  label: string;
  size: number;
}

function VideoBubble({ stream, muted = false, label, size }: VideoBubbleProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  return (
    <div className="pointer-events-auto flex flex-col items-center gap-1">
      <div
        className="overflow-hidden rounded-full border-2 border-indigo-500 bg-slate-800"
        style={{ width: size, height: size }}
      >
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted={muted}
          className="h-full w-full object-cover"
          style={{ transform: muted ? 'scaleX(-1)' : undefined }}
        />
      </div>
      <span className="text-[8px] text-slate-400 font-mono">{label}</span>
    </div>
  );
}
