import { type ButtonHTMLAttributes } from 'react';

/**
 * Standardized close affordance for panels, modals, and toasts.
 *
 * Renders a single ✕ glyph, with `aria-label` driven by the `label` prop
 * and a `title` that surfaces the keyboard shortcut (e.g. "Close (ESC)").
 * Use this in place of inline `[X]`, `X`, `x`, or text like `ESC` so close
 * affordances stay visually and semantically consistent across the app.
 */
export interface CloseButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible label. Defaults to "Close". */
  label?: string;
  /** Optional keyboard shortcut surfaced via `title` (e.g. "ESC"). */
  shortcut?: string;
}

export function CloseButton({
  onClick,
  label = 'Close',
  shortcut,
  className = '',
  type = 'button',
  ...rest
}: CloseButtonProps) {
  const title = shortcut ? `${label} (${shortcut})` : label;
  return (
    <button
      type={type}
      aria-label={label}
      title={title}
      onClick={onClick}
      className={`text-slate-400 hover:text-white text-sm leading-none p-1 ${className}`.trim()}
      {...rest}
    >
      ✕
    </button>
  );
}
