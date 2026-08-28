import { useState } from 'react'
import { api } from './lib/api'
import { OverviewView } from './views/Overview'
import { IncidentsView } from './views/Incidents'
import { IncidentDetailView } from './views/IncidentDetail'
import { DevicesView } from './views/Devices'
import { DeviceCockpitView } from './views/DeviceCockpit'

type Route =
  | { view: 'overview' }
  | { view: 'incidents' }
  | { view: 'devices' }
  | { view: 'incident'; id: number }
  | { view: 'device'; id: string }

const TABS: { key: Route['view']; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'incidents', label: 'Incidents' },
  { key: 'devices', label: 'Devices' },
]

export default function App() {
  const [route, setRoute] = useState<Route>({ view: 'overview' })
  const [back, setBack] = useState<Route>({ view: 'overview' })
  const [message, setMessage] = useState<string | null>(null)

  const openIncident = (id: number) => {
    setBack(route.view === 'incident' || route.view === 'device' ? back : route)
    setRoute({ view: 'incident', id })
  }
  const openDevice = (id: string) => {
    setBack(route.view === 'incident' || route.view === 'device' ? back : route)
    setRoute({ view: 'device', id })
  }

  const runCoordinatorCheck = async () => {
    setMessage('Requesting a coordinator check…')
    try {
      const result = await api.coordinatorCheck()
      setMessage(
        result.requested
          ? 'Coordinator check requested. The result appears in the event log within a few seconds.'
          : (result.detail ?? 'Could not send the request.'),
      )
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    }
  }

  const activeTab: Route['view'] =
    route.view === 'incident' ? 'incidents' : route.view === 'device' ? 'devices' : route.view

  return (
    <div className="app">
      <header className="top">
        <h1>Mesh Sentinel</h1>
        <div className="toolbar">
          <button className="btn" onClick={runCoordinatorCheck}>
            Coordinator check
          </button>
          <span className="version">local diagnostics · nothing leaves this host</span>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? 'active' : ''}
            onClick={() => setRoute({ view: tab.key } as Route)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {message && (
        <div className="notice" style={{ marginBottom: 14 }}>
          {message}{' '}
          <button className="btn link" onClick={() => setMessage(null)}>
            dismiss
          </button>
        </div>
      )}

      {route.view === 'overview' && (
        <OverviewView onOpenIncident={openIncident} onOpenDevice={openDevice} />
      )}
      {route.view === 'incidents' && <IncidentsView onOpenIncident={openIncident} />}
      {route.view === 'devices' && <DevicesView onOpenDevice={openDevice} />}
      {route.view === 'incident' && (
        <IncidentDetailView
          incidentId={route.id}
          onBack={() => setRoute(back)}
          onOpenDevice={openDevice}
        />
      )}
      {route.view === 'device' && (
        <DeviceCockpitView
          deviceId={route.id}
          onBack={() => setRoute(back)}
          onOpenIncident={openIncident}
          onOpenDevice={openDevice}
        />
      )}
    </div>
  )
}
