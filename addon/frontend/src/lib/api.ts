/**
 * API client.
 *
 * Home Assistant Ingress mounts the app under a generated path prefix, so
 * every request is resolved relative to wherever this page happens to live.
 */

export function apiBase(): string {
  const path = window.location.pathname
  const dir = path.endsWith('/') ? path : path.replace(/[^/]*$/, '')
  return `${dir}api`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? `: ${detail}` : ''}`)
  }
  return (await response.json()) as T
}

export type DeviceState = 'healthy' | 'degraded' | 'offline' | 'unknown'

export interface Device {
  id: string
  name: string
  ieee: string | null
  vendor: string | null
  model: string | null
  integration: string
  network_id: string
  device_type: string
  power_source: string
  availability: string
  availability_since: number | null
  last_seen: number | null
  linkquality: number | null
  battery: number | null
  parent_id: string | null
  is_critical: boolean
  disabled: boolean
  supported: boolean
  state: DeviceState
}

export interface Incident {
  id: number
  kind: string
  status: 'open' | 'resolved'
  severity: 'info' | 'warning' | 'error' | 'critical'
  title: string
  conclusion: string
  recommended_action: string
  confidence: number
  started_at: number
  updated_at: number
  resolved_at: number | null
  superseded_by: number | null
  cause_device_id: string | null
  cause_device_name: string | null
  network_id: string | null
  unknowns: string[]
  device_count: number
  affected_devices: { id: string; name: string }[]
}

export interface Evidence {
  id: number
  ts: number
  kind: string
  description: string
  device_id: string | null
  event_id: number | null
  payload: Record<string, unknown>
}

export interface MeshEvent {
  id: number
  ts: number
  source: string
  event_type: string
  device_id: string | null
  network_id: string | null
  severity: string
  payload: Record<string, unknown>
}

export interface NetworkSummary {
  id: string
  label: string
  total: number
  offline: number
  degraded: number
  healthy: number
  routers: number
  battery: number
  critical: number
}

export interface SourceStatus {
  enabled: boolean
  connected: boolean
  note?: string
  broker?: string
  base_topic?: string
  url?: string
}

export interface Overview {
  generated_at: number
  version: string
  health: { score: number; status: string; reasons: string[] }
  networks: NetworkSummary[]
  attention: Device[]
  active_incidents: Incident[]
  recent_incidents: Incident[]
  status: {
    started_at: number | null
    last_evaluation: number | null
    edition: string
    retention_days: number
    sources: Record<string, SourceStatus>
  }
}

export interface IncidentDetail {
  incident: Incident
  roles: Record<string, string>
  evidence: Evidence[]
  timeline: MeshEvent[]
  before_after: {
    before_ts: number
    after_ts: number
    before: { topology: TopologySnapshot | null; devices: SnapshotRow[] }
    after: { topology: TopologySnapshot | null; devices: SnapshotRow[] }
  }
}

export interface TopologySnapshot {
  ts: number
  kind: string
  device_count: number
  router_count: number
  nodes?: { device_id: string; friendly_name: string | null; availability?: string }[]
}

export interface SnapshotRow {
  device_id: string
  availability: string
  linkquality: number | null
  battery: number | null
  last_seen: number | null
}

export interface DeviceDetail {
  device: Device
  parent: Device | null
  children: Device[]
  incidents: Incident[]
  events: MeshEvent[]
  thresholds: {
    stale_after_seconds: number
    offline_grace_seconds: number
    linkquality_degraded: number
  }
}

export interface DeviceHistory {
  device_id: string
  since: number
  linkquality: { ts: number; value: number }[]
  battery: { ts: number; value: number }[]
  availability: { ts: number; value: string }[]
}

export const api = {
  overview: () => request<Overview>('/overview'),
  devices: () => request<{ devices: Device[]; summary: NetworkSummary }>('/devices'),
  device: (id: string) => request<DeviceDetail>(`/devices/${encodeURIComponent(id)}`),
  deviceHistory: (id: string, hours = 24) =>
    request<DeviceHistory>(`/devices/${encodeURIComponent(id)}/history?hours=${hours}`),
  setCritical: (id: string, isCritical: boolean) =>
    request<{ is_critical: boolean }>(`/devices/${encodeURIComponent(id)}/critical`, {
      method: 'POST',
      body: JSON.stringify({ is_critical: isCritical }),
    }),
  incidents: (status?: 'open' | 'resolved') =>
    request<{ incidents: Incident[] }>(`/incidents${status ? `?status=${status}` : ''}`),
  incident: (id: number) => request<IncidentDetail>(`/incidents/${id}`),
  events: (limit = 200) => request<{ events: MeshEvent[] }>(`/events?limit=${limit}`),
  evaluate: () => request<unknown>('/evaluate', { method: 'POST' }),
  coordinatorCheck: () =>
    request<{ requested: boolean; detail: string | null }>('/actions/coordinator-check', {
      method: 'POST',
    }),
  networkMap: () =>
    request<{ requested: boolean; detail: string | null }>('/actions/network-map', {
      method: 'POST',
    }),
}
