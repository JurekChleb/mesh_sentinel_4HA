import { api, type SnapshotRow } from '../lib/api'
import { formatAgo, formatDateTime, formatTime, humanEvent, SEVERITY_LABEL } from '../lib/format'
import { ErrorBox, Loading } from '../components/Loading'
import { Pill } from '../components/Pill'
import { usePoll } from '../lib/usePoll'

interface Props {
  incidentId: number
  onBack: () => void
  onOpenDevice: (id: string) => void
}

function byDevice(rows: SnapshotRow[]): Map<string, SnapshotRow> {
  return new Map(rows.map((row) => [row.device_id, row]))
}

export function IncidentDetailView({ incidentId, onBack, onOpenDevice }: Props) {
  const { data, error, loading, reload } = usePoll(() => api.incident(incidentId), 15_000, [incidentId])

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (loading && !data) return <Loading what="the investigation" />
  if (!data) return null

  const { incident, evidence, timeline, before_after: beforeAfter, roles } = data
  const before = byDevice(beforeAfter.before.devices)
  const after = byDevice(beforeAfter.after.devices)
  const deviceIds = Array.from(new Set([...before.keys(), ...after.keys()]))
  const names = new Map(incident.affected_devices.map((d) => [d.id, d.name]))
  if (incident.cause_device_id && incident.cause_device_name) {
    names.set(incident.cause_device_id, incident.cause_device_name)
  }

  return (
    <>
      <div className="crumbs">
        <button className="btn link" onClick={onBack}>
          ← Back to incidents
        </button>
      </div>

      <div className="panel">
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <Pill tone={incident.severity}>{SEVERITY_LABEL[incident.severity] ?? incident.severity}</Pill>
          <Pill tone={incident.status === 'open' ? 'warning' : 'healthy'}>
            {incident.status === 'open' ? 'Active' : 'Resolved'}
          </Pill>
          <span className="muted small">
            Started {formatDateTime(incident.started_at)}
            {incident.resolved_at ? ` · recovered ${formatTime(incident.resolved_at)}` : ''}
          </span>
        </div>
        <h2 style={{ fontSize: 20, marginBottom: 4 }}>{incident.title}</h2>

        <div className="conclusion">
          <div className="label">What we conclude ({Math.round(incident.confidence * 100)}% confidence)</div>
          <div>{incident.conclusion}</div>
        </div>
        <div className="conclusion">
          <div className="label">Recommended action</div>
          <div>{incident.recommended_action}</div>
        </div>
        {incident.unknowns.length > 0 && (
          <div className="conclusion">
            <div className="label">What we could not determine</div>
            <ul className="plain">
              {incident.unknowns.map((unknown) => (
                <li key={unknown}>{unknown}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="muted small" style={{ margin: 0 }}>
          Mesh Sentinel never changes your network by itself: no resets, no re-pairing, no channel changes.
        </p>
      </div>

      <div className="panel">
        <h2>Why we link these together</h2>
        <div className="timeline">
          {evidence.map((item) => (
            <div className="timeline-item" key={item.id}>
              <span className="ts">{formatTime(item.ts)}</span>
              {item.description}
              {item.device_id && (
                <>
                  {' '}
                  <button className="btn link" onClick={() => onOpenDevice(item.device_id!)}>
                    open device
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>Raw timeline</h2>
        <table className="plain">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Device</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {timeline.slice(-80).map((event) => (
              <tr key={event.id}>
                <td className="mono">{formatTime(event.ts)}</td>
                <td>{humanEvent(event.event_type)}</td>
                <td>{event.device_id ? names.get(event.device_id) ?? event.device_id : '—'}</td>
                <td className="muted">{event.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Before / after</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          State 15 minutes before the incident ({formatTime(beforeAfter.before_ts)}) compared with{' '}
          {formatTime(beforeAfter.after_ts)}.
        </p>
        <table className="plain">
          <thead>
            <tr>
              <th>Device</th>
              <th>Before</th>
              <th>After</th>
              <th>Link quality</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {deviceIds.map((id) => {
              const b = before.get(id)
              const a = after.get(id)
              const changed = b?.availability !== a?.availability
              return (
                <tr key={id}>
                  <td>{names.get(id) ?? id}</td>
                  <td>{b?.availability ?? '—'}</td>
                  <td className={changed ? 'changed' : ''}>{a?.availability ?? '—'}</td>
                  <td>
                    {b?.linkquality ?? '—'} → {a?.linkquality ?? '—'}
                  </td>
                  <td className="muted">{roles[id] ?? ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {deviceIds.length === 0 && (
          <p className="muted small">
            No snapshot exists for that window yet - snapshots are taken every 15 minutes.
          </p>
        )}
      </div>

      <p className="muted small">Last updated {formatAgo(incident.updated_at)}.</p>
    </>
  )
}
