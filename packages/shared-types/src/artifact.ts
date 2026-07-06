// Artifact type system — Phase A of the penny → selva-office consolidation
// (docs/penny-migration-plan.md, RFC 0024 P4).
//
// Ported from madfam-org/penny `packages/types/src/artifacts/index.ts`
// @ e0f9901. Penny expressed these as Zod schemas; selva-office has no
// zod dependency and `@selva/shared-types` is hand-written interfaces,
// so the schemas are rewritten as plain types plus narrow runtime
// guards (the only runtime validation Phase B needs). Dates become ISO
// strings per the shared-types convention (see approval.ts), and
// penny's multi-tenant envelope fields (`tenantId`, `conversationId`,
// `createdBy`) are collapsed into optional provenance fields — selva's
// org/agent model owns identity, not the artifact payload.

/** Every artifact type penny's viewer dispatched on. Renderers land
 * phase-by-phase; the union is ported whole so producers can emit any
 * type and the viewer can show an "unsupported" fallback for the rest. */
export const ARTIFACT_TYPES = [
  'chart',
  'table',
  'code',
  'markdown',
  'image',
  'pdf',
  'json',
  'html',
  'video',
  'audio',
  'model',
  'map',
  'text',
  'csv',
  'excel',
  'presentation',
  'diagram',
] as const;

export type ArtifactType = (typeof ARTIFACT_TYPES)[number];

/** Base artifact envelope. `content` is type-specific (see the
 * `*ArtifactContent` shapes below); renderers coerce defensively. */
export interface Artifact {
  id: string;
  type: ArtifactType;
  title: string;
  description?: string;
  /** Type-specific payload; commonly a string for markdown/html/code/text. */
  content: unknown;
  metadata?: Record<string, unknown>;
  version?: number;
  /** Size in bytes, when known. */
  size?: number;
  mimeType?: string;
  /** For externally stored blobs. */
  url?: string;
  thumbnailUrl?: string;
  tags?: string[];
  /** ISO 8601 timestamps (shared-types convention: string dates). */
  createdAt?: string;
  updatedAt?: string;
  /** Provenance: agent or user id that produced the artifact. */
  createdBy?: string;
  /** Provenance: conversation / task the artifact came from. */
  sourceId?: string;
  exportFormats?: string[];
}

// ── Type-specific content shapes ─────────────────────────────────

export type ChartKind =
  | 'line'
  | 'bar'
  | 'pie'
  | 'scatter'
  | 'area'
  | 'bubble'
  | 'radar'
  | 'treemap'
  | 'heatmap'
  | 'gauge';

export interface ChartAxisConfig {
  label: string;
  type?: 'category' | 'value' | 'time';
}

export interface ChartArtifactContent {
  chartType: ChartKind;
  data: Array<Record<string, unknown>>;
  config?: {
    title?: string;
    xAxis?: ChartAxisConfig;
    yAxis?: ChartAxisConfig;
    colors?: string[];
    legend?: boolean;
    tooltip?: boolean;
    theme?: 'light' | 'dark';
  };
}

export interface TableColumn {
  key: string;
  title: string;
  type?: 'string' | 'number' | 'boolean' | 'date' | 'object';
  sortable?: boolean;
  filterable?: boolean;
  width?: number;
  align?: 'left' | 'center' | 'right';
  /** Date/number format hint. */
  format?: string;
}

export interface TableArtifactContent {
  columns: TableColumn[];
  data: Array<Record<string, unknown>>;
  config?: {
    pagination?: { enabled?: boolean; pageSize?: number };
    sorting?: {
      enabled?: boolean;
      defaultSort?: { column: string; direction: 'asc' | 'desc' };
    };
    filtering?: { enabled?: boolean; searchable?: boolean };
  };
}

export interface CodeArtifactContent {
  code: string;
  language: string;
  filename?: string;
  config?: {
    showLineNumbers?: boolean;
    highlightLines?: number[];
    wordWrap?: boolean;
  };
}

export interface ImageArtifactContent {
  src: string;
  alt?: string;
  width?: number;
  height?: number;
}

export interface MapMarker {
  id: string;
  position: { lat: number; lng: number };
  title?: string;
  description?: string;
}

export interface MapArtifactContent {
  center: { lat: number; lng: number };
  zoom?: number;
  markers?: MapMarker[];
}

/** markdown/html/code-as-string payloads may arrive either as a bare
 * string or as an object keyed by format (penny emitted both). */
export interface MarkdownArtifactContent {
  markdown: string;
}

export interface HtmlArtifactContent {
  html: string;
}

// ── Typed artifact aliases ───────────────────────────────────────

export interface ChartArtifact extends Artifact {
  type: 'chart';
  content: ChartArtifactContent;
}

export interface TableArtifact extends Artifact {
  type: 'table';
  content: TableArtifactContent;
}

export interface CodeArtifact extends Artifact {
  type: 'code';
  content: CodeArtifactContent | string;
}

export interface MarkdownArtifact extends Artifact {
  type: 'markdown';
  content: MarkdownArtifactContent | string;
}

export interface HtmlArtifact extends Artifact {
  type: 'html';
  content: HtmlArtifactContent | string;
}

export interface ImageArtifact extends Artifact {
  type: 'image';
  content: ImageArtifactContent;
}

export interface MapArtifact extends Artifact {
  type: 'map';
  content: MapArtifactContent;
}

// ── Collections & actions (ported envelope, trimmed to consumers) ─

export type ArtifactActionKind =
  | 'create'
  | 'update'
  | 'delete'
  | 'share'
  | 'export'
  | 'version'
  | 'annotate';

export interface ArtifactAction {
  type: ArtifactActionKind;
  artifactId: string;
  userId: string;
  data?: Record<string, unknown>;
  /** ISO 8601. */
  timestamp: string;
}

export interface ArtifactCollection {
  id: string;
  name: string;
  description?: string;
  /** Artifact ids. */
  artifacts: string[];
  tags?: string[];
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
}

// ── Runtime guards (replace penny's zod .parse for Phase B needs) ─

export function isArtifactType(value: unknown): value is ArtifactType {
  return typeof value === 'string' && (ARTIFACT_TYPES as readonly string[]).includes(value);
}

/** Structural check that an unknown payload is a renderable artifact.
 * Intentionally shallow: `content` stays `unknown` and renderers
 * coerce their own payload shape defensively. */
export function isArtifact(value: unknown): value is Artifact {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === 'string' &&
    typeof v.title === 'string' &&
    isArtifactType(v.type) &&
    'content' in v
  );
}

/** Coerce a markdown artifact's content to its source string. */
export function markdownSource(artifact: Artifact): string {
  if (typeof artifact.content === 'string') return artifact.content;
  const c = artifact.content as Partial<MarkdownArtifactContent> | null;
  return typeof c?.markdown === 'string' ? c.markdown : '';
}

/** Coerce an html artifact's content to its source string. */
export function htmlSource(artifact: Artifact): string {
  if (typeof artifact.content === 'string') return artifact.content;
  const c = artifact.content as Partial<HtmlArtifactContent> | null;
  return typeof c?.html === 'string' ? c.html : '';
}
