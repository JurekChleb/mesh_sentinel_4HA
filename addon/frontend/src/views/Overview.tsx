import { api, type Overview as OverviewData } from '../lib/api'
import { formatAgo, formatTime } from '../lib/format'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { IncidentCard } from '../components/IncidentCard'
import { Pill } from '../components/Pill'
import { usePoll } from '../lib/usePoll'

interface Props {
  onOpenIncident: (id: number) => void
  onOpenDevice: (id: string) => void
}

function chainFor(data: OverviewData, incidentId: number): string | undefined {
  const incident = [...data.active_incidents, ...data.recent_incidents].find((i) => i.id === incidentId)
  if (!incident) return undefined
  const parts = [`${formatTime(incident.started_at)} detected`]
  if (incident.cause_device_name) parts.push(`cause: ${incident.cause_device_name}`)
  parts.push(`${incident.device_count} device${incident.device_count === 1 ? '' : 's'} affected`)
  if (incident.resolved_at) parts.push(`${formatTime(incident.resolved_at)} recovery`)
  return parts.join(' → ')
}

export function OverviewView({ onOpenIncident, onOpenDevice }: Props) {
  const { data, error, loading, reload } = usePoll(() => api.overview(), 10_000, [])

  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (loading && !data) return <Loading what="the network overview" />
  if (!data) return null

  const attention = data.attention
  const sources = data.status.sources

  return (
    <>
      <div className="panel">
        <div className="grid-3">
          <div className="stat">
            <span className={`value score-${data.health.status}`}>{data.health.score}/100</span>
            <span className="label">Network health</span>
          </div>
          <div className="stat">
            <span className="value">{data.active_incidents.length}</span>
            <span className="label">
              {data.active_incidents.length === 1 ? 'Active incident' : 'Active incidents'}
            </span>
          </div>
          <div className="stat">
            <span className="value">{attention.length}</span>
            <span className="label">Devices need attention</span>
          </div>
        </div>
        {data.health.reasons.length > 0 && (
          <ul className="plain small muted" style={{ marginTop: 12 }}>
            {data.health.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h2>Integrations</h2>
        <div className="rows">
          {data.networks.map((network) => (
            <div className="row" key={network.id}>
              <div className="grow">
                <div className="name">{network.label}</div>
                <div className="sub">
                  {network.total} devices · {network.routers} routers · {network.battery} on battery
                </div>
              </div>
              <Pill tone="healthy" dot>
                {network.healthy} healthy
              </Pill>
              <Pill tone={network.degraded ? 'degraded' : 'unknown'} dot>
                {network.degraded} degraded
              </Pill>
              <Pill tone={network.offline ? 'offline' : 'unknown'} dot>
                {network.offline} offline
              </Pill>
            </div>
          ))}
          <div className="row">
            <div className="grow">
              <div className="name">Zigbee2MQTT source</div>
              <div className="sub">
                {sources.zigbee2mqtt?.broker} · topic {sources.zigbee2mqtt?.base_topic}
              </div>
            </div>
            <Pill tone={sources.zigbee2mqtt?.connected ? 'healthy' : 'critical'} dot>
              {sources.zigbee2mqtt?.connected ? 'Connected' : 'Not connected'}
            </Pill>
          </div>
          <div className="row">
            <div className="grow">
              <div className="name">ZHA</div>
              <div className="sub">{sources.zha?.note ?? 'Not enabled'}</div>
            </div>
            <Pill tone="unknown">Planned</Pill>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Latest incidents</h2>
        {data.recent_incidents.length === 0 ? (
          <Empty>No incidents recorded yet. That is the good outcome.</Empty>
        ) : (
          data.recent_incidents.map((incident) => (
            <IncidentCard
              key={incident.id}
              incident={incident}
              onOpen={onOpenIncident}
              chain={chainFor(data, incident.id)}
            />
          ))
        )}
      </div>

      {attention.length > 0 && (
        <div className="panel">
          <h2>Devices that need attention</h2>
          <div className="rows">
            {attention.map((device) => (
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
                    {device.vendor ?? 'unknown vendor'} · last seen {formatAgo(device.last_seen, data.generated_at)}
                  </div>
                </div>
                <Pill tone={device.state} dot>
                  {device.state}
                </Pill>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="muted small" style={{ marginTop: 14 }}>
        {data.status.edition === 'free' ? 'Free edition' : 'Pro edition'} · history kept{' '}
        {data.status.retention_days} days · last detection pass{' '}
        {formatAgo(data.status.last_evaluation, data.generated_at)}
      </p>
    </>
  )
}
