import { describe, it, expect, expectTypeOf } from 'vitest';
import { ARTIFACT_TYPES, isArtifact, isArtifactType, markdownSource, htmlSource } from '../index';
import type {
  Artifact,
  ArtifactType,
  MarkdownArtifact,
  HtmlArtifact,
  ChartArtifact,
  TableArtifact,
  ArtifactAction,
  ArtifactCollection,
} from '../index';

const base = {
  id: 'art-1',
  title: 'Example',
  content: 'hello',
};

describe('ARTIFACT_TYPES / isArtifactType', () => {
  it("ports penny's full 17-type union", () => {
    expect(ARTIFACT_TYPES).toHaveLength(17);
    expect(ARTIFACT_TYPES).toContain('markdown');
    expect(ARTIFACT_TYPES).toContain('html');
    expect(ARTIFACT_TYPES).toContain('chart');
  });

  it('accepts every declared type and rejects others', () => {
    for (const t of ARTIFACT_TYPES) {
      expect(isArtifactType(t)).toBe(true);
    }
    expect(isArtifactType('spreadsheet')).toBe(false);
    expect(isArtifactType(42)).toBe(false);
    expect(isArtifactType(undefined)).toBe(false);
  });

  it('narrows to ArtifactType', () => {
    expectTypeOf(ARTIFACT_TYPES[0]).toMatchTypeOf<ArtifactType>();
  });
});

describe('isArtifact', () => {
  it('accepts a minimal well-formed artifact', () => {
    expect(isArtifact({ ...base, type: 'markdown' })).toBe(true);
  });

  it('accepts artifacts with optional envelope fields', () => {
    const full: Artifact = {
      ...base,
      type: 'html',
      description: 'd',
      metadata: { origin: 'test' },
      version: 2,
      tags: ['a'],
      createdAt: '2026-07-06T00:00:00Z',
      createdBy: 'agent-7',
      sourceId: 'task-9',
    };
    expect(isArtifact(full)).toBe(true);
  });

  it('rejects wrong shapes', () => {
    expect(isArtifact(null)).toBe(false);
    expect(isArtifact('markdown')).toBe(false);
    expect(isArtifact({ ...base, type: 'nope' })).toBe(false);
    expect(isArtifact({ ...base })).toBe(false); // missing type
    expect(isArtifact({ id: 1, title: 'x', type: 'html', content: '' })).toBe(false);
    const { content: _content, ...noContent } = { ...base, type: 'html' };
    expect(isArtifact(noContent)).toBe(false);
  });
});

describe('content coercion helpers', () => {
  it('markdownSource handles bare-string and object payloads', () => {
    const bare: MarkdownArtifact = { ...base, type: 'markdown' };
    const keyed: MarkdownArtifact = {
      ...base,
      type: 'markdown',
      content: { markdown: '# hi' },
    };
    expect(markdownSource(bare)).toBe('hello');
    expect(markdownSource(keyed)).toBe('# hi');
    expect(markdownSource({ ...base, type: 'markdown', content: 7 })).toBe('');
    expect(markdownSource({ ...base, type: 'markdown', content: null })).toBe('');
  });

  it('htmlSource handles bare-string and object payloads', () => {
    const bare: HtmlArtifact = { ...base, type: 'html' };
    const keyed: HtmlArtifact = {
      ...base,
      type: 'html',
      content: { html: '<p>hi</p>' },
    };
    expect(htmlSource(bare)).toBe('hello');
    expect(htmlSource(keyed)).toBe('<p>hi</p>');
    expect(htmlSource({ ...base, type: 'html', content: {} })).toBe('');
  });
});

describe('typed artifact shapes (compile-time)', () => {
  it('chart and table artifacts carry typed content', () => {
    const chart: ChartArtifact = {
      ...base,
      type: 'chart',
      content: {
        chartType: 'bar',
        data: [{ x: 'a', y: 1 }],
        config: { legend: true, xAxis: { label: 'X' } },
      },
    };
    const table: TableArtifact = {
      ...base,
      type: 'table',
      content: {
        columns: [{ key: 'n', title: 'N', type: 'number' }],
        data: [{ n: 1 }],
      },
    };
    expect(isArtifact(chart)).toBe(true);
    expect(isArtifact(table)).toBe(true);
    expectTypeOf(chart.content.chartType).toMatchTypeOf<string>();
    expectTypeOf(table.content.columns[0].key).toMatchTypeOf<string>();
  });

  it('action and collection envelopes type-check', () => {
    const action: ArtifactAction = {
      type: 'export',
      artifactId: 'art-1',
      userId: 'u-1',
      timestamp: '2026-07-06T00:00:00Z',
    };
    const collection: ArtifactCollection = {
      id: 'col-1',
      name: 'Reports',
      artifacts: ['art-1'],
    };
    expect(action.type).toBe('export');
    expect(collection.artifacts).toHaveLength(1);
  });
});
