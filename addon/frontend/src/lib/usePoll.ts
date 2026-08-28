import { useCallback, useEffect, useState } from 'react'

/** Fetch once, then refresh on an interval. Errors surface, they do not hide. */
export function usePoll<T>(loader: () => Promise<T>, intervalMs = 10_000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const result = await loader()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    let active = true
    setLoading(true)
    void load()
    const timer = setInterval(() => {
      if (active) void load()
    }, intervalMs)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [load, intervalMs])

  return { data, error, loading, reload: load }
}
