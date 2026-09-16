import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchApi } from '../utils/apiClient'
import type { Notification, NotificationId, NotificationsResponse } from '../types/api'

// The notification domain types live in types/api.ts; re-exported so existing
// `import { type NotificationId } from '.../hooks/useNotifications'` keeps working.
export type { Notification, NotificationId }

/** Query filters for the notifications list endpoint. */
export interface NotificationFilters {
  unread_only?: boolean
  category?: string | null
  priority?: string | null
  limit?: number
  offset?: number
}


/**
 * Hook to fetch notifications
 */
export function useNotifications(filters: NotificationFilters = {}) {
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
    queryFn: () => fetchApi<NotificationsResponse>(`/v1/notifications${queryString ? `?${queryString}` : ''}`),
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
    queryFn: () => fetchApi<{ unread_count?: number | null; [key: string]: unknown }>('/v1/notifications/stats'),
    staleTime: 10000,
    refetchInterval: 30000
  })
}

/**
 * Hook to get a single notification
 */
export function useNotification(notificationId?: NotificationId) {
  return useQuery({
    queryKey: ['notifications', notificationId],
    queryFn: () => fetchApi<Notification>(`/v1/notifications/${notificationId}`),
    enabled: !!notificationId
  })
}

/**
 * Hook to create a new notification
 */
export function useCreateNotification() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (notification: unknown) =>
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
    mutationFn: (notificationId: NotificationId) =>
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
    mutationFn: (category: string | null = null) => {
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
    mutationFn: (notificationId: NotificationId) =>
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
    mutationFn: (notificationId: NotificationId) =>
      fetchApi(`/v1/notifications/${notificationId}`, {
        method: 'DELETE'
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}
