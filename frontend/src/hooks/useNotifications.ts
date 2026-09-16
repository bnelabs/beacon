import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchApi } from '../utils/apiClient'
import type { NotificationId, NotificationsResponse } from '../types/api'

// Dead-export note: useNotificationStats, useNotification,
// useCreateNotification, useDismissNotification and useDeleteNotification
// were removed (zero callers in src/ — NotificationBell's "dismiss" marks
// read, which is what the backend's dismiss-vs-read split actually offers
// the UI today). scripts/check_frontend_hook_reachability.mjs guards the
// remaining set.

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
