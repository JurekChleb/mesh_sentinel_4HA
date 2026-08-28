export function formatTime(ts: number | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatAgo(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return 'never'
  const seconds = Math.max(0, now - ts)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`
  return `${(seconds / 86400).toFixed(1)} d`
}

export function humanEvent(eventType: string): string {
  return eventType.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

export const SEVERITY_LABEL: Record<string, string> = {
  critical: 'Critical',
  error: 'Serious',
  warning: 'Warning',
  info: 'Info',
}
