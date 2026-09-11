import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

/**
 * Live job updates over the backend WebSocket, with a polling fallback.
 *
 * The socket is dialled **same-origin**. nginx serves the SPA and proxies
 * `/api/` to the backend with the `Upgrade`/`Connection` headers (see
 * `frontend/nginx.conf`), so the browser must connect to the page's own host.
 * The previous version hard-coded port 8000, while the backend is published on
 * 3456 and reached through the proxy on 9876 — nothing listened on 8000, so the
 * handshake could never complete in the Docker deployment.
 */

const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_DELAY_MS = 3000
const FALLBACK_POLL_INTERVAL_MS = 5000

export function useJobsWebSocket(options = {}) {
  const { enabled = true, onUpdate, onError } = options

  // Connection state is React state, not a read of `wsRef` during render. A ref
  // mutation does not re-render, so the earlier version could never report a
  // live socket and the "Live updates active" badge never appeared.
  const [isConnected, setIsConnected] = useState(false)

  const wsRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const pollTimerRef = useRef(null)
  const reconnectAttemptsRef = useRef(0)
  const queryClient = useQueryClient()

  // Callbacks are held in refs so that an inline `onUpdate` prop — which is what
  // the Jobs page passes — does not give `connect` a new identity on every
  // render and tear the socket down and back up in a loop.
  const onUpdateRef = useRef(onUpdate)
  const onErrorRef = useRef(onError)
  useEffect(() => {
    onUpdateRef.current = onUpdate
  }, [onUpdate])
  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  const updateJobInCache = useCallback((jobUpdate) => {
    // The payload carries both `id` and `job_id`, because the two caches below
    // are keyed differently.
    queryClient.setQueryData(['jobs', jobUpdate.job_id], (old) =>
      old ? { ...old, ...jobUpdate } : old
    )

    queryClient.setQueryData(['jobs'], (old) =>
      Array.isArray(old)
        ? old.map((job) =>
            job.job_id === jobUpdate.job_id || job.id === jobUpdate.job_id
              ? { ...job, ...jobUpdate }
              : job
          )
        : old
    )

    if (onUpdateRef.current) {
      onUpdateRef.current(jobUpdate)
    }
  }, [queryClient])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (!enabled || wsRef.current) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/v1/jobs/ws`

    let ws
    try {
      ws = new WebSocket(wsUrl)
    } catch (err) {
      console.error('[JobsWebSocket] Failed to create connection:', err)
      if (onErrorRef.current) {
        onErrorRef.current(err)
      }
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0
      stopPolling() // a live socket supersedes the polling fallback
      setIsConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'job_update' && data.job) {
          updateJobInCache(data.job)
        }
        // A "ping" frame is a keepalive and needs no reply or action.
      } catch (err) {
        console.error('[JobsWebSocket] Failed to parse message:', err)
      }
    }

    ws.onerror = (error) => {
      console.error('[JobsWebSocket] Error:', error)
      if (onErrorRef.current) {
        onErrorRef.current(error)
      }
    }

    ws.onclose = () => {
      wsRef.current = null
      setIsConnected(false)

      if (!enabled) {
        return
      }

      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttemptsRef.current += 1
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          connect()
        }, RECONNECT_DELAY_MS)
      } else if (!pollTimerRef.current) {
        // Out of retries: keep the list fresh by polling rather than going silent.
        console.warn('[JobsWebSocket] Reconnect attempts exhausted; falling back to polling')
        pollTimerRef.current = setInterval(() => {
          queryClient.invalidateQueries({ queryKey: ['jobs'] })
        }, FALLBACK_POLL_INTERVAL_MS)
      }
    }
  }, [enabled, updateJobInCache, queryClient, stopPolling])

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    stopPolling()

    const ws = wsRef.current
    if (ws) {
      // Detach the handler first: an intentional close must not schedule a
      // reconnection, which is what an unguarded onclose would do on unmount.
      ws.onclose = null
      ws.close()
      wsRef.current = null
    }
    setIsConnected(false)
  }, [stopPolling])

  useEffect(() => {
    if (enabled) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, connect, disconnect])

  return {
    isConnected,
    reconnect: connect,
    disconnect
  }
}
