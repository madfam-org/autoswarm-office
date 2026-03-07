'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage } from '@autoswarm/shared-types';
import { gameEventBus } from '@/game/PhaserGame';

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (content: string) => void;
  localSessionId: string;
}

function formatTime(timestamp: number): string {
  const d = new Date(timestamp);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function ChatPanel({ messages, onSend, localSessionId }: ChatPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [chatFocused, setChatFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages.length]);

  // Emit chat-focus events for GamepadManager
  useEffect(() => {
    gameEventBus.emit('chat-focus', chatFocused);
  }, [chatFocused]);

  // Global keyboard shortcut: T or / to focus chat
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (chatFocused) return;
      if (e.key === 't' || e.key === 'T' || e.key === '/') {
        // Don't capture if user is in another input
        const target = e.target as HTMLElement;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        setCollapsed(false);
        setChatFocused(true);
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [chatFocused]);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = inputValue.trim();
      if (!trimmed) return;
      onSend(trimmed);
      setInputValue('');
    },
    [inputValue, onSend],
  );

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === 'Escape') {
      setChatFocused(false);
      inputRef.current?.blur();
    }
  }, []);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute bottom-4 left-4 z-hud rounded bg-slate-800/90 px-3 py-1 text-xs text-slate-300 retro-btn hover:bg-slate-700"
      >
        Chat [T]
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 left-4 z-hud flex w-full max-w-80 flex-col rounded border border-slate-700 bg-slate-900/95 shadow-lg sm:w-80">
      <div className="flex items-center justify-between border-b border-slate-700 px-3 py-1">
        <span className="text-xs font-semibold text-slate-400">CHAT</span>
        <button
          onClick={() => setCollapsed(true)}
          className="text-xs text-slate-500 hover:text-slate-300"
          aria-label="Collapse chat"
        >
          _
        </button>
      </div>

      <div
        ref={listRef}
        className="flex h-48 flex-col gap-0.5 overflow-y-auto px-3 py-2 text-xs"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col justify-center gap-2 opacity-40">
            <div className="h-2.5 w-3/4 animate-pulse rounded bg-slate-700" />
            <div className="h-2.5 w-1/2 animate-pulse rounded bg-slate-700" />
            <div className="h-2.5 w-2/3 animate-pulse rounded bg-slate-700" />
          </div>
        )}
        {messages.map((msg, i) => {
          const isLocal = msg.senderSessionId === localSessionId;
          if (msg.isSystem) {
            return (
              <div
                key={msg.id}
                className="text-center text-slate-500 italic text-[9px] py-0.5 animate-fade-in-up"
                style={{ animationDelay: `${Math.min(i, 5) * 50}ms` }}
              >
                {msg.content}
              </div>
            );
          }
          return (
            <div
              key={msg.id}
              className={`flex ${isLocal ? 'justify-end' : 'justify-start'} animate-fade-in-up`}
              style={{ animationDelay: `${Math.min(i, 5) * 50}ms` }}
            >
              <div className={`max-w-[85%] rounded px-2 py-1 ${isLocal ? 'bg-indigo-900/50' : 'bg-slate-800/60'}`}>
                <div className="flex items-baseline gap-1.5">
                  <span className={`font-semibold text-[9px] ${isLocal ? 'text-indigo-400' : 'text-emerald-400'}`}>
                    {msg.senderName}
                  </span>
                  <span className="text-slate-600 text-[8px]">{formatTime(msg.timestamp)}</span>
                </div>
                <span className="text-slate-300">{msg.content}</span>
              </div>
            </div>
          );
        })}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-slate-700 p-2">
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onFocus={() => setChatFocused(true)}
          onBlur={() => setChatFocused(false)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message... (T to focus, Esc to unfocus)"
          maxLength={500}
          className="w-full rounded bg-slate-800 px-2 py-1 text-xs text-slate-200 placeholder-slate-500 outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </form>
    </div>
  );
}
