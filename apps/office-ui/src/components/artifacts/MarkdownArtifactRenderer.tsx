'use client';

import { useMemo, useState, type FC } from 'react';
import { markdownSource, type Artifact } from '@selva/shared-types';

/**
 * Read-only markdown artifact renderer — Phase B of the penny →
 * selva-office consolidation (docs/penny-migration-plan.md).
 *
 * Adapted from madfam-org/penny
 * `apps/web/src/components/artifacts/renderers/MarkdownRenderer.tsx`
 * @ e0f9901, with two deliberate changes:
 *
 * 1. SECURITY: penny piped the raw markdown through its regex parser
 *    into `dangerouslySetInnerHTML` without escaping, so any inline
 *    HTML (e.g. `<img onerror=…>`) executed verbatim. Here the source
 *    is HTML-escaped BEFORE the markdown transforms run, so only
 *    markup this parser itself emits can reach the DOM.
 * 2. Heading ids are slugified consistently (penny stamped raw titles
 *    as ids but linked to slugs, so its TOC anchors never matched).
 */

export interface MarkdownArtifactRendererProps {
  artifact: Artifact;
  className?: string;
}

function escapeHtml(source: string): string {
  return source
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function slugifyHeading(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-');
}

/** Minimal markdown → HTML transform over pre-escaped text. Penny's
 * parser, kept dependency-free; a real markdown library is a Phase C
 * decision alongside the chart library (migration plan §7). */
export function renderMarkdown(source: string): string {
  const escaped = escapeHtml(source);
  return (
    escaped
      // Headers (ids slugified so TOC anchors resolve)
      .replace(/^### (.*)$/gim, (_, t: string) => `<h3 id="${slugifyHeading(t)}">${t}</h3>`)
      .replace(/^## (.*)$/gim, (_, t: string) => `<h2 id="${slugifyHeading(t)}">${t}</h2>`)
      .replace(/^# (.*)$/gim, (_, t: string) => `<h1 id="${slugifyHeading(t)}">${t}</h1>`)
      // Code blocks, then inline code
      .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // Links (escaped source, so quotes cannot break out of href;
      // scheme allowlist so javascript:/data: URLs render as text)
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (whole, text: string, href: string) =>
        /^(https?:|mailto:|#|\/)/i.test(href)
          ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`
          : whole,
      )
      // Bold and italic
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      // Unordered lists
      .replace(/^\* (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>[\s\S]*<\/li>)/, '<ul>$1</ul>')
      // Blockquotes
      .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
      // Line breaks
      .replace(/\n/g, '<br />')
  );
}

interface Heading {
  level: number;
  title: string;
  id: string;
}

export const MarkdownArtifactRenderer: FC<MarkdownArtifactRendererProps> = ({
  artifact,
  className = '',
}) => {
  const source = markdownSource(artifact);
  const [showToc, setShowToc] = useState(false);

  const html = useMemo(() => renderMarkdown(source), [source]);

  const headings = useMemo<Heading[]>(() => {
    const out: Heading[] = [];
    const re = /^(#{1,6})\s+(.*)$/gm;
    let match: RegExpExecArray | null;
    while ((match = re.exec(source)) !== null) {
      out.push({
        level: match[1].length,
        title: match[2],
        id: slugifyHeading(match[2]),
      });
    }
    return out;
  }, [source]);

  return (
    <div className={`flex h-full w-full ${className}`.trim()} data-testid="markdown-artifact">
      {showToc && headings.length > 0 && (
        <nav
          aria-label="Table of contents"
          className="w-56 shrink-0 overflow-auto border-r border-slate-700 bg-slate-800/60 p-3"
        >
          {headings.map((h) => (
            <a
              key={h.id}
              href={`#${h.id}`}
              className="block rounded px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
              style={{ paddingLeft: `${h.level * 8}px` }}
            >
              {h.title}
            </a>
          ))}
        </nav>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800/60 px-3 py-2">
          <span className="text-xs text-slate-400">
            Markdown · {source.split('\n').length} lines
          </span>
          {headings.length > 0 && (
            <button
              type="button"
              onClick={() => setShowToc((v) => !v)}
              aria-pressed={showToc}
              className="rounded px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
            >
              Contents
            </button>
          )}
        </div>
        <div
          className="markdown-artifact-body flex-1 overflow-auto p-4 text-sm leading-relaxed text-slate-200 [&_a]:text-cyan-400 [&_a]:underline [&_blockquote]:border-l-4 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_blockquote]:italic [&_code]:rounded [&_code]:bg-slate-800 [&_code]:px-1 [&_h1]:text-xl [&_h1]:font-bold [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:text-base [&_h3]:font-semibold [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-slate-800 [&_pre]:p-3 [&_ul]:list-disc [&_ul]:pl-5"
          // Safe: `html` is produced by renderMarkdown, which escapes the
          // source before emitting a fixed set of tags.
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    </div>
  );
};
