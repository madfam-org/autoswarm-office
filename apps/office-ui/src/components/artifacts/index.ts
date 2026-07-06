/**
 * Artifact viewer module — penny → selva-office consolidation
 * (docs/penny-migration-plan.md). Everything here ships dark behind
 * `NEXT_PUBLIC_ARTIFACTS_ENABLED` until reviewed + QA'd.
 */

export { ArtifactViewer, type ArtifactViewerProps } from './ArtifactViewer';
export {
  MarkdownArtifactRenderer,
  renderMarkdown,
  slugifyHeading,
  type MarkdownArtifactRendererProps,
} from './MarkdownArtifactRenderer';
export { HtmlArtifactRenderer, type HtmlArtifactRendererProps } from './HtmlArtifactRenderer';

/** Feature flag (migration plan §4): default OFF; opt in explicitly. */
export function artifactsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ARTIFACTS_ENABLED === 'true';
}
