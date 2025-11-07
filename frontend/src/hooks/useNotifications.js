import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE = '/api'

async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  })

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({ detail: 'Request failed' }))
    const detail = errorPayload.detail
    let message

    if (typeof detail === 'string') {
      message = detail
    } else if (detail?.user_friendly) {
      message = detail.user_friendly
    } else {
      message = `HTTP ${response.status}`
    }

    throw new Error(message)
  }

  return response.json()
}

/**
 * Hook to fetch notifications
 */
export function useNotifications(filters = {}) {
  const {
    unread_only = false,
    category = null,
    priority = null,
    limit = 50,
    offset = 0
  } = filters

  const params = new URLSearchParams()
  if (unread_only) params.set('unread_only', 'true')
  if (category) params.set('category', category)
  if (priority) params.set('priority', priority)
  if (limit) params.set('limit', limit.toString())
  if (offset) params.set('offset', offset.toString())

  const queryString = params.toString()

  return useQuery({
    queryKey: ['notifications', filters],
    queryFn: () => fetchApi(`/v1/notifications${queryString ? `?${queryString}` : ''}`),
    staleTime: 10000, // 10 seconds
    refetchInterval: 30000 // Refetch every 30 seconds
  })
}

/**
 * Hook to fetch notification stats
 */
export function useNotificationStats() {
  return useQuery({
    queryKey: ['notifications', 'stats'],
    queryFn: () => fetchApi('/v1/notifications/stats'),
    staleTime: 10000,
    refetchInterval: 30000
  })
}

/**
 * Hook to get a single notification
 */
export function useNotification(notificationId) {
  return useQuery({
    queryKey: ['notifications', notificationId],
    queryFn: () => fetchApi(`/v1/notifications/${notificationId}`),
    enabled: !!notificationId
  })
}

/**
 * Hook to create a new notification
 */
export function useCreateNotification() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (notification) =>
      fetchApi('/v1/notifications', {
        method: 'POST',
        body: JSON.stringify(notification)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}

/**
 * Hook to mark a notification as read
 */
export function useMarkNotificationAsRead() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (notificationId) =>
      fetchApi(`/v1/notifications/${notificationId}/read`, {
        method: 'POST'
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}

/**
 * Hook to mark all notifications as read
 */
export function useMarkAllAsRead() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (category = null) => {
      const params = category ? `?category=${category}` : ''
      return fetchApi(`/v1/notifications/read-all${params}`, {
        method: 'POST'
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}

/**
 * Hook to dismiss a notification
 */
export function useDismissNotification() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (notificationId) =>
      fetchApi(`/v1/notifications/${notificationId}/dismiss`, {
        method: 'POST'
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}

/**
 * Hook to delete a notification
 */
export function useDeleteNotification() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (notificationId) =>
      fetchApi(`/v1/notifications/${notificationId}`, {
        method: 'DELETE'
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}
