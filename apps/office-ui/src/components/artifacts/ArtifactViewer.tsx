'use client';

import { Component, type FC, type ReactNode } from 'react';
import { isArtifact, type Artifact } from '@selva/shared-types';
import { MarkdownArtifactRenderer } from './MarkdownArtifactRenderer';
import { HtmlArtifactRenderer } from './HtmlArtifactRenderer';

/**
 * Artifact viewer dispatcher — Phase B of the penny → selva-office
 * consolidation (docs/penny-migration-plan.md, RFC 0024 P4).
 *
 * Adapted from madfam-org/penny
 * `apps/web/src/components/artifacts/ArtifactViewer.tsx` @ e0f9901,
 * trimmed to the Phase B slice: an error boundary plus dispatch for
 * the two read-only renderers ported so far (`markdown`, `html`).
 * Every other artifact type in the union falls through to an explicit
 * "not yet supported" card; renderers are added per migration-plan
 * Phase C. Penny's ArtifactHeader / export / share toolbar belongs to
 * the interactive shell (Phase D) and is deliberately not ported here.
 *
 * Gate any mount behind `NEXT_PUBLIC_ARTIFACTS_ENABLED` (see
 * `artifactsEnabled()` in ./index.ts).
 */

export interface ArtifactViewerProps {
  /** Validated or unvalidated payload; non-artifacts render an error card. */
  artifact: Artifact | unknown;
  className?: string;
}

class ArtifactErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <FallbackCard
          tone="error"
          title="Artifact failed to render"
          body={this.state.error.message}
          action={
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="mt-3 rounded bg-semantic-error px-3 py-1 text-xs text-white hover:opacity-90"
            >
              Try again
            </button>
          }
        />
      );
    }
    return this.props.children;
  }
}

const FallbackCard: FC<{
  tone: 'error' | 'muted';
  title: string;
  body: string;
  action?: ReactNode;
}> = ({ tone, title, body, action }) => (
  <div
    role={tone === 'error' ? 'alert' : 'note'}
    className={`flex h-full min-h-[8rem] w-full items-center justify-center rounded border p-4 text-center ${
      tone === 'error'
        ? 'border-semantic-error-dark bg-semantic-error/10'
        : 'border-slate-700 bg-slate-800/40'
    }`}
  >
    <div>
      <p
        className={`text-sm font-semibold ${
          tone === 'error' ? 'text-semantic-error-light' : 'text-slate-200'
        }`}
      >
        {title}
      </p>
      <p className="mt-1 text-xs text-slate-400">{body}</p>
      {action}
    </div>
  </div>
);

const Dispatch: FC<{ artifact: Artifact }> = ({ artifact }) => {
  switch (artifact.type) {
    case 'markdown':
      return <MarkdownArtifactRenderer artifact={artifact} />;
    case 'html':
      return <HtmlArtifactRenderer artifact={artifact} />;
    default:
      return (
        <FallbackCard
          tone="muted"
          title="Unsupported artifact type"
          body={`"${artifact.type}" artifacts are not renderable yet (migration plan Phase C).`}
        />
      );
  }
};

export const ArtifactViewer: FC<ArtifactViewerProps> = ({ artifact, className = '' }) => {
  if (!isArtifact(artifact)) {
    return (
      <FallbackCard
        tone="error"
        title="Invalid artifact"
        body="The payload is not a recognizable artifact envelope."
      />
    );
  }

  return (
    <section
      aria-label={`Artifact: ${artifact.title}`}
      className={`flex h-full w-full flex-col overflow-hidden rounded border border-slate-700 bg-slate-900 ${className}`.trim()}
    >
      <header className="flex items-center justify-between border-b border-slate-700 bg-slate-800 px-3 py-2">
        <h3 className="truncate text-sm font-semibold text-slate-100">{artifact.title}</h3>
        <span className="ml-2 shrink-0 rounded bg-slate-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
          {artifact.type}
        </span>
      </header>
      <div className="min-h-0 flex-1">
        <ArtifactErrorBoundary>
          <Dispatch artifact={artifact} />
        </ArtifactErrorBoundary>
      </div>
    </section>
  );
};
