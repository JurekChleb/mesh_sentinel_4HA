export function Loading({ what = 'data' }: { what?: string }) {
  return <p className="empty">Loading {what}…</p>
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="notice warn">
      <strong>Could not reach the Mesh Sentinel backend.</strong>
      <div className="small mono" style={{ marginTop: 6 }}>
        {error}
      </div>
      {onRetry && (
        <button className="btn" style={{ marginTop: 10 }} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>
}
