'use client';

/**
 * AtriumOverlay — top-level mount point for the Atrium subsystem.
 *
 * Sits inside the office shell (NOT a Next.js route) and renders:
 *  - the dock on the left edge (always visible)
 *  - all open EcosystemWindows in z-order (low z first → high z on top)
 *  - the bottom taskbar with chips for every open window
 *  - the first-time intro hint
 *
 * The overlay container is `pointer-events: none` so the office canvas
 * stays interactive between windows. Children opt back in with
 * `pointer-events: auto` on their own elements.
 *
 * The whole subsystem is sandboxed inside one `<aside>` so it can be
 * mounted/unmounted as a unit during demos or accessibility audits.
 */

import { EcosystemWindow } from './EcosystemWindow';
import { AtriumDock } from './AtriumDock';
import { AtriumTaskbar } from './AtriumTaskbar';
import { AtriumIntroHint } from './AtriumIntroHint';
import {
  selectWindowsZOrdered,
  useAtriumStore,
} from '@/stores/atrium-windows';

export function AtriumOverlay() {
  const windows = useAtriumStore((s) => s.windows);
  const focusedSlug = useAtriumStore((s) => s.focusedSlug);
  const ordered = selectWindowsZOrdered({ windows });

  return (
    <aside
      data-testid="atrium-overlay"
      aria-label="MADFAM Ecosystem Atrium"
      className="pointer-events-none fixed inset-0 z-30"
    >
      {/* Dock — anchored top-left under the HUD. The HUD owns the
          true top bar; we sit just below it on the left edge. */}
      <div className="pointer-events-none absolute left-0 top-32 z-40">
        <AtriumDock />
      </div>

      <AtriumIntroHint />

      {/* Open windows in z-order. Each window is absolute-positioned
          and opt-ins to pointer-events itself. */}
      <div className="pointer-events-none absolute inset-0">
        {ordered.map((w) => (
          <div key={w.slug} className="pointer-events-auto">
            <EcosystemWindow window={w} isFocused={focusedSlug === w.slug} />
          </div>
        ))}
      </div>

      <AtriumTaskbar />
    </aside>
  );
}
