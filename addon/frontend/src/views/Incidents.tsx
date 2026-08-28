import { useState } from 'react'
import { api } from '../lib/api'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { IncidentCard } from '../components/IncidentCard'
import { usePoll } from '../lib/usePoll'

export function IncidentsView({ onOpenIncident }: { onOpenIncident: (id: number) => void }) {
  const [filter, setFilter] = useState<'all' | 'open' | 'resolved'>('all')
  const { data, error, loading, reload } = usePoll(
    () => api.incidents(filter === 'all' ? undefined : filter),
    15_000,
    [filter],
  )

  return (
    <div className="panel">
      <div className="toolbar" style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0, flex: 1 }}>Incidents</h2>
        {(['all', 'open', 'resolved'] as const).map((value) => (
          <button
            key={value}
            className={`btn ${filter === value ? 'primary' : ''}`}
            onClick={() => setFilter(value)}
          >
            {value === 'all' ? 'All' : value === 'open' ? 'Active' : 'Resolved'}
          </button>
        ))}
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="incidents" />}
      {data && data.incidents.length === 0 && (
        <Empty>Nothing recorded in this view.</Empty>
      )}
      {data?.incidents.map((incident) => (
        <IncidentCard key={incident.id} incident={incident} onOpen={onOpenIncident} />
      ))}
    </div>
  )
}
