import { useState, type MouseEvent, type ReactNode } from 'react'
import Badge from './ui/Badge'
import Button from './ui/Button'
import {
  useNotifications,
  useMarkNotificationAsRead,
  useMarkAllAsRead
} from '../hooks/useNotifications'
import type { Notification, NotificationId } from '../types/api'
import { useRouter } from '../store/useRouter'

interface NotificationItemProps {
  notification: Notification
  onRead: (id: NotificationId) => void
  onDismiss: (id: NotificationId) => void
}

function NotificationItem({ notification, onRead, onDismiss }: NotificationItemProps) {
  const navigate = useRouter((state) => state.navigate)

  const getIcon = (type?: string | null): ReactNode => {
    switch (type) {
      case 'success':
        return (
          <svg className="w-5 h-5 text-bne-moss" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      case 'error':
        return (
          <svg className="w-5 h-5 text-bne-clay" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      case 'warning':
        return (
          <svg className="w-5 h-5 text-bne-ochre" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        )
      case 'alert':
        return (
          <svg className="w-5 h-5 text-bne-clay animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
        )
      default:
        return (
          <svg className="w-5 h-5 text-bne-pine" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
    }
  }

  const handleClick = () => {
    if (!notification.is_read) {
      onRead(notification.id)
    }

    if (notification.action_url) {
      // Parse action URL and navigate
      const url = notification.action_url
      if (url.startsWith('/')) {
        const path = url.substring(1).split('?')[0]
        navigate(path)
      }
    }
  }

  const formatTime = (dateString?: string | null) => {
    // The cast keeps the exact runtime of the untyped original for the two
    // degenerate inputs: `new Date(null)` is the epoch, `new Date(undefined)`
    // is Invalid Date. A missing created_at renders the same as before.
    const date = new Date(dateString as string)
    const now = new Date()
    const diff = Math.floor((now.getTime() - date.getTime()) / 1000) // seconds

    if (diff < 60) return 'Just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div
      className={`px-4 py-3 border-b border-bne-line hover:bg-bne-paper/50 transition-colors cursor-pointer ${
        !notification.is_read ? 'bg-bne-pine/5' : ''
      }`}
      onClick={handleClick}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 mt-1">{getIcon(notification.notification_type)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className={`text-sm ${!notification.is_read ? 'font-semibold' : 'font-medium'} text-bne-ink`}>
              {notification.title}
            </p>
            {notification.is_urgent && (
              <Badge variant="danger" size="sm">
                Urgent
              </Badge>
            )}
          </div>
          <p className="text-xs text-bne-muted mt-1 line-clamp-2">{notification.message}</p>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs text-bne-muted">{formatTime(notification.created_at)}</span>
            {notification.category && (
              <Badge variant="default" size="sm">
                {notification.category}
              </Badge>
            )}
            {notification.action_label && (
              <span className="text-xs text-bne-pine font-medium">{notification.action_label} →</span>
            )}
          </div>
        </div>
        {!notification.is_read && (
          <button
            onClick={(e: MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              onDismiss(notification.id)
            }}
            className="flex-shrink-0 p-1 hover:bg-bne-paper-dim rounded transition-colors"
          >
            <svg className="w-4 h-4 text-bne-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}

export default function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false)
  const { data: notificationsData } = useNotifications({ unread_only: false, limit: 20 })
  const markAsReadMutation = useMarkNotificationAsRead()
  const markAllAsReadMutation = useMarkAllAsRead()

  const notifications = notificationsData?.notifications || []
  const unreadCount = notificationsData?.unread_count || 0

  // Polling lives in the hook (useNotifications sets refetchInterval: 30s).
  // A second component-level setInterval used to refetch on its own 30s
  // cycle, doubling the request rate out of phase with the hook's.

  const handleMarkAsRead = (id: NotificationId) => {
    markAsReadMutation.mutate(id)
  }

  const handleDismiss = (id: NotificationId) => {
    markAsReadMutation.mutate(id)
  }

  const handleMarkAllAsRead = () => {
    // `null` category = mark every category read, same as the hook's default.
    markAllAsReadMutation.mutate(null)
  }

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 hover:bg-bne-paper-dim rounded-lg transition-colors"
      >
        <svg className="w-6 h-6 text-bne-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-bne-clay text-bne-chalk text-xs font-bold rounded-full flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-2 w-96 max-h-[600px] rounded-md bg-bne-card shadow-bne-card border border-bne-line z-40 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bne-line bg-bne-paper/30">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-bne-ink">Notifications</h3>
                {unreadCount > 0 && (
                  <Button variant="ghost" size="sm" onClick={handleMarkAllAsRead} disabled={markAllAsReadMutation.isPending}>
                    Mark all read
                  </Button>
                )}
              </div>
            </div>

            <div className="overflow-y-auto flex-1">
              {notifications.length === 0 ? (
                <div className="text-center py-12">
                  <svg
                    className="w-16 h-16 mx-auto text-bne-muted/30 mb-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                    />
                  </svg>
                  <p className="text-sm text-bne-muted">No notifications</p>
                </div>
              ) : (
                notifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onRead={handleMarkAsRead}
                    onDismiss={handleDismiss}
                  />
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
