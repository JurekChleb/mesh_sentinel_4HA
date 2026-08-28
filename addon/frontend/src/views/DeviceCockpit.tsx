import { useState } from 'react'
import { api } from '../lib/api'
import { formatAgo, formatDateTime, formatDuration, humanEvent } from '../lib/format'
import { ErrorBox, Loading } from '../components/Loading'
import { IncidentCard } from '../components/IncidentCard'
import { Pill } from '../components/Pill'
import { Sparkline } from '../components/Sparkline'
import { usePoll } from '../lib/usePoll'

interface Props {
  deviceId: string
  onBack: () => void
  onOpenIncident: (id: number) => void
  onOpenDevice: (id: string) => void
}

export function DeviceCockpitView({ deviceId, onBack, onOpenIncident, onOpenDevice }: Props) {
  const [busy, setBusy] = useState(false)
  const { data, error, loading, reload } = usePoll(() => api.device(deviceId), 15_000, [deviceId])
  const history = usePoll(() => api.deviceHistory(deviceId, 24), 60_000, [deviceId])

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (loading && !data) return <Loading what="the device" />
  if (!data) return null

  const { device, parent, children, incidents, events, thresholds } = data

  const toggleCritical = async () => {
    setBusy(true)
    try {
      await api.setCritical(device.id, !device.is_critical)
      await reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="crumbs">
        <button className="btn link" onClick={onBack}>
          ← Back
        </button>
      </div>

      <div className="panel">
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, flex: 1, fontSize: 20 }}>{device.name}</h2>
          <Pill tone={device.state} dot>
            {device.state}
          </Pill>
          <button className="btn" onClick={toggleCritical} disabled={busy}>
            {device.is_critical ? 'Unmark critical' : 'Mark as critical'}
          </button>
        </div>

        <dl className="kv">
          <dt>Last seen</dt>
          <dd>
            {formatAgo(device.last_seen)} <span className="muted">({formatDateTime(device.last_seen)})</span>
          </dd>
          <dt>Availability</dt>
          <dd>
            {device.availability} since {formatDateTime(device.availability_since)}
          </dd>
          <dt>Type</dt>
          <dd>
            {device.device_type.replace('_', ' ')} · {device.power_source}
          </dd>
          <dt>Hardware</dt>
          <dd>
            {device.vendor ?? '—'} {device.model ?? ''} <span className="mono muted">{device.ieee ?? ''}</span>
          </dd>
          <dt>Link quality</dt>
          <dd>{device.linkquality ?? '—'}</dd>
          <dt>Battery</dt>
          <dd>{device.battery !== null ? `${device.battery}%` : '—'}</dd>
          <dt>Routed via</dt>
          <dd>
            {parent ? (
              <button className="btn link" onClick={() => onOpenDevice(parent.id)}>
                {parent.name}
              </button>
            ) : (
              <span className="muted">Unknown — run a network map scan to record routing</span>
            )}
          </dd>
          <dt>Marked offline after</dt>
          <dd>
            {formatDuration(thresholds.stale_after_seconds)} of silence
            <span className="muted"> (+{thresholds.offline_grace_seconds}s before it becomes an incident)</span>
          </dd>
        </dl>

        {children.length > 0 && (
          <>
            <h3>Devices routing through this one</h3>
            <div className="rows">
              {children.map((child) => (
                <div className="row clickable" key={child.id} onClick={() => onOpenDevice(child.id)}>
                  <div className="grow">
                    <div className="name">{child.name}</div>
                  </div>
                  <Pill tone={child.state} dot>
                    {child.state}
                  </Pill>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="panel">
        <h2>Link quality, last 24 hours</h2>
        <Sparkline
          points={history.data?.linkquality ?? []}
          threshold={thresholds.linkquality_degraded}
          label="link quality"
        />
        {device.power_source === 'battery' && (
          <>
            <h3>Battery</h3>
            <Sparkline points={history.data?.battery ?? []} label="battery" />
          </>
        )}
      </div>

      <div className="panel">
        <h2>Incidents involving this device</h2>
        {incidents.length === 0 ? (
          <p className="muted small">None recorded.</p>
        ) : (
          incidents.map((incident) => (
            <IncidentCard key={incident.id} incident={incident} onOpen={onOpenIncident} />
          ))
        )}
      </div>

      <div className="panel">
        <h2>Recent events</h2>
        <table className="plain">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Severity</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td className="mono">{formatDateTime(event.ts)}</td>
                <td>{humanEvent(event.event_type)}</td>
                <td>{event.severity}</td>
                <td className="muted small">
                  {typeof event.payload.message === 'string'
                    ? event.payload.message
                    : typeof event.payload.reason === 'string'
                      ? event.payload.reason
                      : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {events.length === 0 && <p className="muted small">No events recorded yet.</p>}
      </div>
    </>
  )
}
