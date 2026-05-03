'use client';

import { useState, useEffect } from 'react';

const TABS = [
  { id: 'office', label: 'Office', icon: '\u{1F3E2}' },
  { id: 'chat', label: 'Chat', icon: '\u{1F4AC}' },
  { id: 'tasks', label: 'Tasks', icon: '\u{1F4CB}' },
  { id: 'settings', label: 'Settings', icon: '\u2699\uFE0F' },
] as const;

interface MobileNavProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export function MobileNav({ activeTab, onTabChange }: MobileNavProps) {
  const [mounted, setMounted] = useState(false);
  const [isTouch, setIsTouch] = useState(false);

  // Suppress rendering until first effect runs to avoid SSR/CSR
  // hydration flash where useTouchDetection flips false → true.
  useEffect(() => {
    setMounted(true);
    setIsTouch('ontouchstart' in window || navigator.maxTouchPoints > 0);
  }, []);

  if (!mounted || !isTouch) return null;

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-hud flex border-t border-slate-700 bg-slate-900/95 backdrop-blur-sm safe-area-pb"
      aria-label="Mobile navigation"
    >
      {TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`touch-target flex flex-1 flex-col items-center gap-0.5 py-2 text-[8px] font-mono transition-colors ${
            activeTab === tab.id ? 'text-indigo-400' : 'text-slate-500'
          }`}
          aria-label={tab.label}
          aria-current={activeTab === tab.id ? 'page' : undefined}
        >
          <span className="text-base" aria-hidden="true">{tab.icon}</span>
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
