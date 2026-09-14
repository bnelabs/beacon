import { cn } from '../../utils/cn'
import Button from './Button'

export default function ErrorMessage({
  title = 'Something went wrong',
  message,
  error,
  onRetry,
  className
}) {
  const displayMessage = message || error?.message || 'An unexpected error occurred'

  return (
    <div
      className={cn(
        'rounded-md border border-bne-clay/30 border-l-[3px] border-l-bne-clay bg-bne-clay-50/60 p-5',
        className
      )}
    >
      <div className="flex items-start gap-3">
        <svg
          className="h-6 w-6 text-bne-clay flex-shrink-0 mt-0.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <div className="flex-1">
          <h3 className="font-semibold text-bne-clay mb-1">{title}</h3>
          <p className="text-sm text-bne-muted">{displayMessage}</p>
          {onRetry && (
            <div className="mt-4">
              <Button variant="outline" size="sm" onClick={onRetry}>
                Try Again
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
