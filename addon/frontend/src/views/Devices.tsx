import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { formatAgo } from '../lib/format'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { Pill } from '../components/Pill'
import { usePoll } from '../lib/usePoll'

export function DevicesView({ onOpenDevice }: { onOpenDevice: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [onlyProblems, setOnlyProblems] = useState(false)
  const { data, error, loading, reload } = usePoll(() => api.devices(), 15_000, [])

  const devices = useMemo(() => {
    const all = data?.devices ?? []
    const needle = query.trim().toLowerCase()
    return all
      .filter((d) => (onlyProblems ? d.state !== 'healthy' : true))
      .filter((d) =>
        needle
          ? [d.name, d.vendor, d.model, d.ieee].some((f) => f?.toLowerCase().includes(needle))
          : true,
      )
  }, [data, query, onlyProblems])

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (loading && !data) return <Loading what="devices" />

  return (
    <div className="panel">
      <div className="toolbar" style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Devices</h2>
        <input
          className="search"
          placeholder="Search by name, vendor, model or IEEE"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className={`btn ${onlyProblems ? 'primary' : ''}`} onClick={() => setOnlyProblems((v) => !v)}>
          Only problems
        </button>
      </div>

      {devices.length === 0 ? (
        <Empty>No devices match.</Empty>
      ) : (
        <div className="rows">
          {devices.map((device) => (
            <div
              className="row clickable"
              key={device.id}
              onClick={() => onOpenDevice(device.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && onOpenDevice(device.id)}
            >
              <div className="grow">
                <div className="name">
                  {device.name} {device.is_critical && <Pill tone="critical">Critical</Pill>}
                </div>
                <div className="sub">
                  {device.device_type.replace('_', ' ')} · {device.vendor ?? '—'} {device.model ?? ''} · last seen{' '}
                  {formatAgo(device.last_seen)}
                </div>
              </div>
              {device.battery !== null && <span className="muted small">{device.battery}%</span>}
              {device.linkquality !== null && <span className="muted small">LQI {device.linkquality}</span>}
              <Pill tone={device.state} dot>
                {device.state}
              </Pill>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
