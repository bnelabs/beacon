import { useEffect, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'

/**
 * WebSocket hook for real-time job updates
 * Falls back to polling if WebSocket connection fails
 */
export function useJobsWebSocket(options = {}) {
  const { enabled = true, onUpdate, onError } = options
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const reconnectAttemptsRef = useRef(0)
  const queryClient = useQueryClient()

  const MAX_RECONNECT_ATTEMPTS = 5
  const RECONNECT_DELAY = 3000
  const FALLBACK_POLL_INTERVAL = 5000

  const updateJobInCache = useCallback((jobUpdate) => {
    // Update individual job query
    queryClient.setQueryData(['jobs', jobUpdate.job_id], (old) => {
      if (!old) return old
      return { ...old, ...jobUpdate }
    })

    // Update jobs list query
    queryClient.setQueryData(['jobs'], (old) => {
      if (!old) return old
      return old.map(job =>
        (job.job_id === jobUpdate.job_id || job.id === jobUpdate.job_id)
          ? { ...job, ...jobUpdate }
          : job
      )
    })

    // Trigger callback if provided
    if (onUpdate) {
      onUpdate(jobUpdate)
    }
  }, [queryClient, onUpdate])

  const connect = useCallback(() => {
    if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    try {
      // Use ws:// for local development, wss:// for production
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.hostname}:8000/api/v1/jobs/ws`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[JobsWebSocket] Connected')
        reconnectAttemptsRef.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'job_update' && data.job) {
            updateJobInCache(data.job)
          } else if (data.type === 'ping') {
            // Heartbeat - ignore
          }
        } catch (err) {
          console.error('[JobsWebSocket] Failed to parse message:', err)
        }
      }

      ws.onerror = (error) => {
        console.error('[JobsWebSocket] Error:', error)
        if (onError) {
          onError(error)
        }
      }

      ws.onclose = () => {
        console.log('[JobsWebSocket] Disconnected')
        wsRef.current = null

        // Attempt reconnection
        if (enabled && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log(`[JobsWebSocket] Reconnecting (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`)
            connect()
          }, RECONNECT_DELAY)
        } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          console.warn('[JobsWebSocket] Max reconnection attempts reached, falling back to polling')
          // Fall back to polling by invalidating queries periodically
          reconnectTimeoutRef.current = setInterval(() => {
            queryClient.invalidateQueries({ queryKey: ['jobs'] })
          }, FALLBACK_POLL_INTERVAL)
        }
      }
    } catch (err) {
      console.error('[JobsWebSocket] Failed to create connection:', err)
      if (onError) {
        onError(err)
      }
    }
  }, [enabled, updateJobInCache, queryClient, onError])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      if (typeof reconnectTimeoutRef.current === 'number') {
        // Polling interval
        clearInterval(reconnectTimeoutRef.current)
      } else {
        // Reconnect timeout
        clearTimeout(reconnectTimeoutRef.current)
      }
      reconnectTimeoutRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (enabled) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, connect, disconnect])

  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
    reconnect: connect,
    disconnect
  }
}
