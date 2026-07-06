'use client';

import { ArtifactViewer, artifactsEnabled } from '@/components/artifacts';
import type { Artifact } from '@selva/shared-types';

/**
 * Flag-gated artifact viewer preview — the Phase B mount for the
 * penny → selva-office consolidation (docs/penny-migration-plan.md).
 *
 * With `NEXT_PUBLIC_ARTIFACTS_ENABLED` unset/false (the default) this
 * page renders a "disabled" notice, so shipping it is a no-op for
 * production. With the flag on, it exercises every renderer ported so
 * far against sample payloads — the QA surface the plan requires
 * before the flag defaults on. Real producer wiring (agents emitting
 * artifacts into office surfaces) is Phase D/F.
 */

const SAMPLES: Artifact[] = [
  {
    id: 'sample-markdown',
    type: 'markdown',
    title: 'Markdown sample',
    content: [
      '# Consolidation notes',
      '',
      '## Why',
      'Penny is **superseded**; its artifact layer moves here.',
      '',
      '## Status',
      '* Phase A: types ported',
      '* Phase B: `markdown` + `html` renderers, flagged',
      '',
      '> Raw HTML like <img src=x onerror=alert(1)> is escaped, not executed.',
      '',
      'See the [migration plan](https://github.com/madfam-org/selva-office/blob/main/docs/penny-migration-plan.md).',
    ].join('\n'),
  },
  {
    id: 'sample-html',
    type: 'html',
    title: 'HTML sample (sandboxed)',
    content: {
      html: '<h1 style="font-family: sans-serif">Sandboxed HTML</h1><p style="font-family: sans-serif">Rendered via <code>srcDoc</code> in an origin-isolated iframe.</p>',
    },
  },
  {
    id: 'sample-chart',
    type: 'chart',
    title: 'Chart sample (Phase C — not yet renderable)',
    content: { chartType: 'bar', data: [{ month: 'Jan', value: 4 }] },
  },
];

export default function ArtifactsPreviewPage() {
  if (!artifactsEnabled()) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
        <div className="max-w-md rounded border border-slate-700 bg-slate-900 p-6 text-center">
          <h1 className="text-lg font-semibold text-slate-100">Artifacts are not enabled</h1>
          <p className="mt-2 text-sm text-slate-400">
            Set{' '}
            <code className="rounded bg-slate-800 px-1">NEXT_PUBLIC_ARTIFACTS_ENABLED=true</code> to
            preview the artifact viewer (penny consolidation, Phase B).
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 p-6">
      <h1 className="mb-1 text-xl font-bold text-slate-100">Artifact viewer preview</h1>
      <p className="mb-6 text-sm text-slate-400">
        Phase B QA surface — sample artifacts rendered through{' '}
        <code className="rounded bg-slate-800 px-1">ArtifactViewer</code>.
      </p>
      <div className="grid gap-6 lg:grid-cols-2">
        {SAMPLES.map((artifact) => (
          <div key={artifact.id} className="h-96">
            <ArtifactViewer artifact={artifact} />
          </div>
        ))}
      </div>
    </main>
  );
}
