/**
 * Shared time-formatting helpers.
 *
 * Centralizes the variations that were previously reimplemented in
 * ChatPanel, SimplifiedView, ApprovalPanel, CalendarPanel, OpsFeed,
 * MetricsDashboard, and DashboardPanel. Keeping these here ensures a
 * consistent localization story (locale-aware via `toLocaleTimeString`)
 * and one place to fix bugs.
 *
 * Inputs accept Date, ISO string, or epoch ms — caller convenience.
 * All helpers return an empty string on parse failure rather than
 * throwing, so they can be used safely inside JSX without wrappers.
 */

type TimeInput = Date | string | number;

function toDate(input: TimeInput): Date | null {
  try {
    const d = input instanceof Date ? input : new Date(input);
    if (Number.isNaN(d.getTime())) return null;
    return d;
  } catch {
    return null;
  }
}

/**
 * Format as `HH:MM` using the user's locale.
 *
 * Used for lightweight chat-message timestamps where seconds would be
 * noise and where the message itself carries the date context.
 */
export function formatHM(input: TimeInput): string {
  const d = toDate(input);
  if (!d) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Format as `HH:MM:SS` using the user's locale.
 *
 * Used for event-stream timestamps (OpsFeed, dashboard timeline) where
 * second-level granularity matters for ordering.
 */
export function formatHMS(input: TimeInput): string {
  const d = toDate(input);
  if (!d) return '';
  return d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * Relative time in coarse buckets: "Xs ago", "Xm ago", "Xh ago", "Xd ago".
 *
 * Adapted from the previous ApprovalPanel implementation, which was the
 * most thoughtful of the duplicate variants. Chosen over more elaborate
 * libraries (date-fns, dayjs) because the buckets here are sufficient
 * for queue UIs and we avoid pulling in a 30 KB dependency.
 */
export function timeAgo(input: TimeInput): string {
  const d = toDate(input);
  if (!d) return '';
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds < 0) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
