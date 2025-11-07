import { useState, useEffect } from 'react'
import Badge from './ui/Badge'
import Card, { CardHeader, CardTitle, CardContent } from './ui/Card'
import Button from './ui/Button'
import { useNotifications, useMarkNotificationAsRead, useMarkAllAsRead } from '../hooks/useNotifications'
import { useRouter } from '../store/useRouter'

function NotificationItem({ notification, onRead, onDismiss }) {
  const navigate = useRouter((state) => state.navigate)

  const getIcon = (type) => {
    switch (type) {
      case 'success':
        return (
          <svg className="w-5 h-5 text-bne-emerald" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      case 'error':
        return (
          <svg className="w-5 h-5 text-bne-crimson" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      case 'warning':
        return (
          <svg className="w-5 h-5 text-bne-amber" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        )
      case 'alert':
        return (
          <svg className="w-5 h-5 text-bne-crimson animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
        )
      default:
        return (
          <svg className="w-5 h-5 text-bne-azure" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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

  const formatTime = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = Math.floor((now - date) / 1000) // seconds

    if (diff < 60) return 'Just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div
      className={`px-4 py-3 border-b border-bne-frost hover:bg-bne-ice/50 transition-colors cursor-pointer ${
        !notification.is_read ? 'bg-bne-azure/5' : ''
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
          <p className="text-xs text-bne-steel mt-1 line-clamp-2">{notification.message}</p>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs text-bne-steel">{formatTime(notification.created_at)}</span>
            {notification.category && (
              <Badge variant="default" size="sm">
                {notification.category}
              </Badge>
            )}
            {notification.action_label && (
              <span className="text-xs text-bne-azure font-medium">{notification.action_label} →</span>
            )}
          </div>
        </div>
        {!notification.is_read && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDismiss(notification.id)
            }}
            className="flex-shrink-0 p-1 hover:bg-bne-frost rounded transition-colors"
          >
            <svg className="w-4 h-4 text-bne-steel" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
  const { data: notificationsData, refetch } = useNotifications({ unread_only: false, limit: 20 })
  const markAsReadMutation = useMarkNotificationAsRead()
  const markAllAsReadMutation = useMarkAllAsRead()

  const notifications = notificationsData?.notifications || []
  const unreadCount = notificationsData?.unread_count || 0

  useEffect(() => {
    // Refresh notifications every 30 seconds
    const interval = setInterval(() => {
      refetch()
    }, 30000)

    return () => clearInterval(interval)
  }, [refetch])

  const handleMarkAsRead = (id) => {
    markAsReadMutation.mutate(id)
  }

  const handleDismiss = (id) => {
    markAsReadMutation.mutate(id)
  }

  const handleMarkAllAsRead = () => {
    markAllAsReadMutation.mutate()
  }

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 hover:bg-bne-frost rounded-lg transition-colors"
      >
        <svg className="w-6 h-6 text-bne-steel" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-bne-crimson text-white text-xs font-bold rounded-full flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-2 w-96 max-h-[600px] rounded-xl bg-white shadow-bne-card border border-bne-frost z-40 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bne-frost bg-bne-ice/30">
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
                    className="w-16 h-16 mx-auto text-bne-steel/30 mb-4"
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
                  <p className="text-sm text-bne-steel">No notifications</p>
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
