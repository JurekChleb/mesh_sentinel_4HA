interface SparklineProps {
  points: { ts: number; value: number }[]
  width?: number
  height?: number
  threshold?: number
  label?: string
}

/** Inline SVG so the app ships no charting dependency. */
export function Sparkline({ points, width = 320, height = 56, threshold, label }: SparklineProps) {
  if (points.length < 2) {
    return <p className="muted small">Not enough history yet{label ? ` for ${label}` : ''}.</p>
  }
  const values = points.map((p) => p.value)
  const min = Math.min(...values, threshold ?? Infinity)
  const max = Math.max(...values, threshold ?? -Infinity)
  const span = max - min || 1
  const firstTs = points[0].ts
  const lastTs = points[points.length - 1].ts
  const tsSpan = lastTs - firstTs || 1

  const x = (ts: number) => ((ts - firstTs) / tsSpan) * (width - 2) + 1
  const y = (value: number) => height - 4 - ((value - min) / span) * (height - 10)
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.ts).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')

  return (
    <svg className="spark" width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {threshold !== undefined && (
        <line
          x1={0}
          x2={width}
          y1={y(threshold)}
          y2={y(threshold)}
          stroke="var(--warning)"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
      )}
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />
    </svg>
  )
}
