'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { OfficeExperience } from '@/components/OfficeExperience';
import { PreJoinScreen, shouldSkipPreJoin } from '@/components/PreJoinScreen';
import { VoiceModeChangeModal } from '@/components/VoiceModeChangeModal';
import { useVoiceMode } from '@/hooks/useVoiceMode';

export default function OfficePage() {
  const router = useRouter();
  const { status, loading } = useVoiceMode();
  const [modalOpen, setModalOpen] = useState(false);
  const [preJoinDone, setPreJoinDone] = useState(false);

  useEffect(() => {
    // Read the skip preference client-side only (SSR-safe).
    setPreJoinDone(shouldSkipPreJoin());
  }, []);

  useEffect(() => {
    if (!loading && status && !status.onboarding_complete) {
      router.replace('/onboarding');
    }
  }, [loading, status, router]);

  if (loading || !status?.onboarding_complete) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
        {loading ? 'Loading office…' : 'Redirecting to onboarding…'}
      </main>
    );
  }

  if (!preJoinDone) {
    return (
      <PreJoinScreen
        spaceName="the office"
        onJoin={() => setPreJoinDone(true)}
      />
    );
  }

  return (
    <>
      <OfficeExperience mode="live" />
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="fixed right-4 top-4 z-hud rounded bg-slate-800/80 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
      >
        Voice mode: {status.voice_mode}
      </button>
      <VoiceModeChangeModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
