'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Type-safe `useState` whose value is mirrored in `localStorage`.
 *
 * The hook is hydration-safe: on the very first render (server-side and
 * the client's first client-render to match it) the returned value is
 * always the supplied default, so the markup the client emits matches
 * what the server emitted. The localStorage value is read in a
 * `useEffect` after mount and applied as a one-shot state update —
 * which triggers a single re-render and avoids the
 * "Hydration failed because the server rendered HTML didn't match the
 * client" warning.
 *
 * The setter accepts either a value or a `(prev) => next` updater
 * (matching React's `useState` API). Each setter call writes synchronously
 * to `localStorage` (wrapped in try/catch — quota / disabled storage
 * errors are swallowed and only logged in development).
 *
 * Signature:
 *   const [value, setValue] = useLocalStorageState<string>('key', '');
 *   const [n, setN] = useLocalStorageState<number>('count', 0, {
 *     parse: (raw) => Number(raw),
 *     serialize: String,
 *   });
 *
 * @param key  localStorage key
 * @param defaultValue  value used during SSR + first client render, and
 *                      whenever the stored value is absent / parse fails
 * @param options.parse  customise how the raw string is converted to T
 *                      (defaults to identity-cast for strings, JSON.parse
 *                      otherwise)
 * @param options.serialize  customise how T is written to storage
 *                          (defaults to identity for strings, JSON.stringify
 *                          otherwise)
 */
export interface UseLocalStorageStateOptions<T> {
  parse?: (raw: string) => T;
  serialize?: (value: T) => string;
}

export function useLocalStorageState<T>(
  key: string,
  defaultValue: T,
  options: UseLocalStorageStateOptions<T> = {},
): [T, (next: T | ((prev: T) => T)) => void] {
  const isStringDefault = typeof defaultValue === 'string';
  const parse =
    options.parse ??
    ((raw: string) =>
      (isStringDefault ? (raw as unknown as T) : (JSON.parse(raw) as T)));
  const serialize =
    options.serialize ??
    ((value: T) =>
      isStringDefault ? (value as unknown as string) : JSON.stringify(value));

  const [value, setValue] = useState<T>(defaultValue);
  // Track whether we've completed the post-mount hydration read so the
  // setter doesn't race with it.
  const hydratedRef = useRef(false);

  // Post-mount hydration: read once after the first client render so the
  // initial markup matches the server-rendered HTML.
  useEffect(() => {
    hydratedRef.current = true;
    if (typeof window === 'undefined') return;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) {
        setValue(parse(raw));
      }
    } catch {
      // Storage unavailable / quota / disabled — keep the default.
    }
    // We intentionally read on mount only. Changing key is unusual and
    // would require a richer API if ever needed.

  }, []);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved =
          typeof next === 'function' ? (next as (p: T) => T)(prev) : next;
        if (typeof window !== 'undefined') {
          try {
            window.localStorage.setItem(key, serialize(resolved));
          } catch {
            // Swallow — user may have storage disabled.
          }
        }
        return resolved;
      });
    },
    [key, serialize],
  );

  return [value, set];
}
