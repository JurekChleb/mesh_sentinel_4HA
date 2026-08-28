import type { Incident } from '../lib/api'
import { formatTime, SEVERITY_LABEL } from '../lib/format'
import { Pill } from './Pill'

interface Props {
  incident: Incident
  onOpen: (id: number) => void
  chain?: string
}

export function IncidentCard({ incident, onOpen, chain }: Props) {
  return (
    <div
      className={`incident-card ${incident.severity}`}
      onClick={() => onOpen(incident.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onOpen(incident.id)}
    >
      <div className="meta">
        <Pill tone={incident.severity}>{SEVERITY_LABEL[incident.severity] ?? incident.severity}</Pill>
        <Pill tone={incident.status === 'open' ? 'warning' : incident.superseded_by ? 'unknown' : 'healthy'}>
          {incident.status === 'open'
            ? 'Active'
            : incident.superseded_by
              ? `Superseded by #${incident.superseded_by}`
              : 'Resolved'}
        </Pill>
        <span className="muted small">
          {formatTime(incident.started_at)} · {Math.round(incident.confidence * 100)}% confidence ·{' '}
          {incident.device_count} device{incident.device_count === 1 ? '' : 's'}
        </span>
      </div>
      <h3>{incident.title}</h3>
      {chain && <div className="chain">{chain}</div>}
      <p className="small" style={{ margin: '8px 0 0' }}>
        {incident.conclusion}
      </p>
    </div>
  )
}
