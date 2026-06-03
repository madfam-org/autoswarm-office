'use client';

import { useState, useEffect, useCallback } from 'react';
import type { AvatarConfig } from '@selva/shared-types';
import { DEFAULT_AVATAR_CONFIG } from '@selva/shared-types';

const STORAGE_KEY = 'selva:avatar-config';

/**
 * Load and save avatar config from localStorage.
 * Falls back to default config if nothing is stored.
 */
export function useAvatarConfig() {
  const [config, setConfig] = useState<AvatarConfig>(DEFAULT_AVATAR_CONFIG);
  const [isFirstVisit, setIsFirstVisit] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as AvatarConfig;
        setConfig(parsed);
      } else {
        setIsFirstVisit(true);
      }
    } catch {
      setIsFirstVisit(true);
    }
  }, []);

  const saveConfig = useCallback((newConfig: AvatarConfig) => {
    setConfig(newConfig);
    setIsFirstVisit(false);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newConfig));
    } catch {
      // localStorage not available
    }
  }, []);

  return { config, saveConfig, isFirstVisit };
}
