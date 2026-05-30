'use client';

import type { FC } from 'react';

import type { GaReadiness } from './types';

const READINESS_STYLES: Record<GaReadiness, string> = {
  ready: 'bg-emerald-900/60 text-emerald-300 border-emerald-700',
  near_ready: 'bg-amber-900/60 text-amber-300 border-amber-700',
  waived: 'bg-sky-900/60 text-sky-300 border-sky-700',
  discovery: 'bg-purple-900/60 text-purple-300 border-purple-700',
  blocked: 'bg-red-900/60 text-red-300 border-red-700',
};

interface TulanaReadinessBadgeProps {
  readiness: GaReadiness | string;
  compact?: boolean;
}

export const TulanaReadinessBadge: FC<TulanaReadinessBadgeProps> = ({
  readiness,
  compact = false,
}) => {
  const key = (readiness in READINESS_STYLES ? readiness : 'discovery') as GaReadiness;
  const label = key.replace('_', ' ');
  return (
    <span
      className={`inline-block rounded border font-mono uppercase ${
        compact ? 'px-1 py-0.5 text-[6px]' : 'px-1.5 py-0.5 text-[7px]'
      } ${READINESS_STYLES[key]}`}
      title={`Tulana GA readiness: ${label}`}
    >
      {label}
    </span>
  );
};
