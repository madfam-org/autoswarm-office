import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  ArtifactViewer,
  MarkdownArtifactRenderer,
  HtmlArtifactRenderer,
  renderMarkdown,
  slugifyHeading,
  artifactsEnabled,
} from '../artifacts';
import type { Artifact } from '@selva/shared-types';

const markdownArtifact: Artifact = {
  id: 'a-md',
  type: 'markdown',
  title: 'Notes',
  content: '# Hello World\n\nSome **bold** text and `code`.',
};

const htmlArtifact: Artifact = {
  id: 'a-html',
  type: 'html',
  title: 'Widget',
  content: { html: '<p>hi from html</p>' },
};

describe('ArtifactViewer', () => {
  it('renders a markdown artifact with title chrome', () => {
    render(<ArtifactViewer artifact={markdownArtifact} />);
    expect(screen.getByRole('region', { name: 'Artifact: Notes' })).toBeInTheDocument();
    expect(screen.getByTestId('markdown-artifact')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Hello World' })).toBeInTheDocument();
    expect(screen.getByText('bold')).toBeInTheDocument();
  });

  it('renders an html artifact into a sandboxed iframe', () => {
    const { container } = render(<ArtifactViewer artifact={htmlArtifact} />);
    const iframe = container.querySelector('iframe');
    expect(iframe).not.toBeNull();
    expect(iframe!.getAttribute('srcdoc')).toBe('<p>hi from html</p>');
    // Hard security invariant: never allow-same-origin.
    expect(iframe!.getAttribute('sandbox') ?? '').not.toContain('allow-same-origin');
  });

  it('shows an unsupported-type card for not-yet-ported renderers', () => {
    render(
      <ArtifactViewer
        artifact={{
          id: 'a-chart',
          type: 'chart',
          title: 'Q3',
          content: { chartType: 'bar', data: [] },
        }}
      />,
    );
    expect(screen.getByText('Unsupported artifact type')).toBeInTheDocument();
    expect(screen.getByText(/Phase C/)).toBeInTheDocument();
  });

  it('rejects payloads that are not artifacts', () => {
    render(<ArtifactViewer artifact={{ nope: true }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid artifact');
  });
});

describe('MarkdownArtifactRenderer', () => {
  it('escapes embedded HTML instead of executing it (XSS)', () => {
    const { container } = render(
      <MarkdownArtifactRenderer
        artifact={{
          id: 'a-xss',
          type: 'markdown',
          title: 'xss',
          content: 'before <img src=x onerror="alert(1)"> after',
        }}
      />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it('accepts object-keyed content and toggles the TOC', () => {
    render(
      <MarkdownArtifactRenderer
        artifact={{
          id: 'a-toc',
          type: 'markdown',
          title: 'toc',
          content: { markdown: '# One\n\n## Two Words' },
        }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Contents' }));
    const nav = screen.getByRole('navigation', { name: 'Table of contents' });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Two Words' })).toHaveAttribute('href', '#two-words');
  });
});

describe('renderMarkdown / slugifyHeading', () => {
  it('slugifies consistently with emitted heading ids (penny TOC bug fix)', () => {
    expect(slugifyHeading('Two Words!')).toBe('two-words');
    expect(renderMarkdown('# Two Words!')).toContain('<h1 id="two-words">');
  });

  it('escapes quotes so markdown links cannot break out of href', () => {
    const html = renderMarkdown('[x](https://a.example/"onclick="x)');
    expect(html).not.toContain('"onclick="');
  });

  it('refuses javascript: link schemes', () => {
    const html = renderMarkdown('[click](javascript:alert(1))');
    expect(html).not.toContain('<a ');
    const ok = renderMarkdown('[docs](https://example.com/x)');
    expect(ok).toContain('href="https://example.com/x"');
  });

  it('renders code blocks, bold, and blockquotes', () => {
    const html = renderMarkdown('```js\nconst a = 1;\n```\n\n**b** and > not a quote\n\n> quoted');
    expect(html).toContain('<pre><code class="language-js">');
    expect(html).toContain('<strong>b</strong>');
    expect(html).toContain('<blockquote>quoted</blockquote>');
  });
});

describe('HtmlArtifactRenderer', () => {
  it('defaults to a fully locked sandbox and supports source view', () => {
    const { container } = render(
      <HtmlArtifactRenderer
        artifact={{
          id: 'a-h',
          type: 'html',
          title: 'h',
          content: '<b>raw</b>',
        }}
      />,
    );
    expect(container.querySelector('iframe')!.getAttribute('sandbox')).toBe('');
    fireEvent.click(screen.getByRole('button', { name: 'source' }));
    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelector('pre')!.textContent).toBe('<b>raw</b>');
  });

  it('only ever grants allow-scripts when opted in', () => {
    const { container } = render(
      <HtmlArtifactRenderer
        artifact={{ id: 'a-h2', type: 'html', title: 'h2', content: '<i>x</i>' }}
        allowScripts
      />,
    );
    expect(container.querySelector('iframe')!.getAttribute('sandbox')).toBe('allow-scripts');
  });
});

describe('artifactsEnabled', () => {
  it('defaults off and only enables on the literal "true"', () => {
    const prev = process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED;
    delete process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED;
    expect(artifactsEnabled()).toBe(false);
    process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED = 'false';
    expect(artifactsEnabled()).toBe(false);
    process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED = 'true';
    expect(artifactsEnabled()).toBe(true);
    if (prev === undefined) delete process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED;
    else process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED = prev;
  });
});
