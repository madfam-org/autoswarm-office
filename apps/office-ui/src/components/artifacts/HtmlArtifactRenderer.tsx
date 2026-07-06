'use client';

import { useState, type FC } from 'react';
import { htmlSource, type Artifact } from '@selva/shared-types';

/**
 * Read-only HTML artifact renderer — Phase B of the penny →
 * selva-office consolidation (docs/penny-migration-plan.md).
 *
 * Adapted from madfam-org/penny
 * `apps/web/src/components/artifacts/renderers/HTMLRenderer.tsx`
 * @ e0f9901, with the sandbox hardened:
 *
 * - Penny document.write()'d the payload into a same-origin iframe and,
 *   in "interactive" mode, set `sandbox="allow-scripts allow-same-origin"`
 *   — that combination lets sandboxed script reach the parent origin,
 *   i.e. no sandbox at all. Here the payload goes in via `srcDoc` and
 *   the sandbox is `allow-scripts` at most, never `allow-same-origin`,
 *   so artifact HTML can never touch the office-ui origin.
 */

export interface HtmlArtifactRendererProps {
  artifact: Artifact;
  /** Allow scripts inside the (origin-isolated) sandbox. Default false. */
  allowScripts?: boolean;
  className?: string;
}

export const HtmlArtifactRenderer: FC<HtmlArtifactRendererProps> = ({
  artifact,
  allowScripts = false,
  className = '',
}) => {
  const [viewMode, setViewMode] = useState<'preview' | 'source'>('preview');
  const source = htmlSource(artifact);

  return (
    <div className={`flex h-full w-full flex-col ${className}`.trim()} data-testid="html-artifact">
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800/60 px-3 py-2">
        <div className="flex items-center gap-1 rounded bg-slate-700/60 p-0.5">
          {(['preview', 'source'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setViewMode(mode)}
              aria-pressed={viewMode === mode}
              className={`rounded px-2 py-1 text-xs capitalize ${
                viewMode === mode
                  ? 'bg-slate-600 text-white shadow'
                  : 'text-slate-300 hover:bg-slate-600/60'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400">HTML · {source.length} chars</span>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {viewMode === 'preview' ? (
          <iframe
            title={`HTML artifact: ${artifact.title}`}
            className="h-full w-full border-0 bg-white"
            // Never add allow-same-origin here — combined with
            // allow-scripts it would void the sandbox entirely.
            sandbox={allowScripts ? 'allow-scripts' : ''}
            srcDoc={source}
          />
        ) : (
          <pre className="h-full overflow-auto whitespace-pre-wrap bg-slate-900 p-4 font-mono text-xs text-slate-200">
            {source}
          </pre>
        )}
      </div>
    </div>
  );
};
