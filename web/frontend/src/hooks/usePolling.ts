import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/client'
import type { Alert } from '../types'

/** One active fetch per effect; the next poll starts after completion, never on an interval. */
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, intervalMs = 2000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const trigger = useRef<() => void>(() => {})
  const refresh = useCallback(() => trigger.current(), [])

  useEffect(() => {
    let disposed = false
    let running = false
    let queued = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | null = null
    setData(null)
    setError('')
    setLoading(true)
    setUpdatedAt(null)

    const run = async () => {
      if (disposed) return
      if (running) { queued = true; return }
      if (timer !== undefined) clearTimeout(timer)
      running = true
      const current = new AbortController()
      controller = current
      try {
        const result = await fetcher(current.signal)
        if (!disposed && !current.signal.aborted) {
          setData(result)
          setError('')
          setUpdatedAt(Date.now())
        }
      } catch (reason) {
        if (!disposed && !current.signal.aborted) setError(errorMessage(reason))
      } finally {
        running = false
        if (!disposed) {
          setLoading(false)
          if (queued) {
            queued = false
            timer = setTimeout(() => { void run() }, 0)
          } else {
            timer = setTimeout(() => { void run() }, intervalMs)
          }
        }
      }
    }

    trigger.current = () => { void run() }
    void run()
    return () => {
      disposed = true
      queued = false
      trigger.current = () => {}
      if (timer !== undefined) clearTimeout(timer)
      controller?.abort()
    }
  }, [fetcher, intervalMs])

  return { data, error, loading, updatedAt, refresh }
}

/**
 * A DOM-render observation in a visible browser tab, not a server ACK or proof
 * that a person saw the alert. Browser clocks must not be subtracted from a
 * different process clock without a synchronization model.
 */
export function useAlertVisibility(alerts: Alert[] | undefined) {
  const recorded = useRef(new Set<number>())
  useEffect(() => {
    let firstFrame = 0
    let secondFrame = 0
    let disposed = false
    const observe = () => {
      if (disposed || document.visibilityState !== 'visible') return
      firstFrame = requestAnimationFrame(() => {
        secondFrame = requestAnimationFrame(() => {
          if (disposed || document.visibilityState !== 'visible') return
          const visible = (alerts ?? []).filter((alert) => {
            if (!alert.ingest || recorded.current.has(alert.ingest.receipt_id)) return false
            const row = document.querySelector<HTMLElement>('[data-alert-id="' + alert.id + '"]')
            if (!row) return false
            const box = row.getBoundingClientRect()
            return box.width > 0 && box.height > 0 && box.bottom > 0 && box.top < window.innerHeight
          })
          if (!visible.length) return
          const observation = {
            stage: 'DOM_RENDERED_VISIBLE_TAB',
            wall_time_ms: Date.now(),
            performance_ms: performance.now(),
            time_origin_ms: performance.timeOrigin,
            alerts: visible.map((alert) => ({
              alert_id: alert.id,
              receipt_id: alert.ingest!.receipt_id,
              event_id: alert.ingest!.event_id,
              data_origin: alert.ingest!.data_origin,
            })),
          }
          visible.forEach((alert) => recorded.current.add(alert.ingest!.receipt_id))
          let previous: unknown[] = []
          try {
            const parsed: unknown = JSON.parse(document.documentElement.dataset.artguardAlertVisibility ?? '[]')
            if (Array.isArray(parsed)) previous = parsed
          } catch { /* A diagnostic entry cannot interrupt the UI. */ }
          document.documentElement.dataset.artguardAlertVisibility = JSON.stringify([...previous, observation].slice(-100))
          window.dispatchEvent(new CustomEvent('artguard:alerts-visible', { detail: observation }))
        })
      })
    }
    observe()
    document.addEventListener('visibilitychange', observe)
    return () => {
      disposed = true
      cancelAnimationFrame(firstFrame)
      cancelAnimationFrame(secondFrame)
      document.removeEventListener('visibilitychange', observe)
    }
  }, [alerts])
}
