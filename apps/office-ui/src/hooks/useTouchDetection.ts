'use client';

import { useState, useEffect } from 'react';

interface TouchInfo {
  isTouchDevice: boolean;
  isPortrait: boolean;
}

/**
 * Detects if the device supports touch input and current orientation.
 */
export function useTouchDetection(): TouchInfo {
  const [info, setInfo] = useState<TouchInfo>({
    isTouchDevice: false,
    isPortrait: false,
  });

  useEffect(() => {
    const checkTouch = () => {
      const isTouch =
        'ontouchstart' in window ||
        navigator.maxTouchPoints > 0;

      const isPortrait = window.innerHeight > window.innerWidth;

      setInfo({ isTouchDevice: isTouch, isPortrait });
    };

    checkTouch();
    window.addEventListener('resize', checkTouch);
    window.addEventListener('orientationchange', checkTouch);

    return () => {
      window.removeEventListener('resize', checkTouch);
      window.removeEventListener('orientationchange', checkTouch);
    };
  }, []);

  return info;
}
