import { useState, useCallback } from 'react'

/**
 * Custom hook for handling errors with retry logic and user-friendly messages
 */
export function useErrorHandler() {
  const [error, setError] = useState(null)

  const handleError = useCallback((err, context = '') => {
    console.error(`Error in ${context}:`, err)

    // Extract user-friendly error from API response
    let errorData = null

    if (err.response?.data?.detail) {
      const detail = err.response.data.detail
      if (typeof detail === 'object') {
        errorData = detail
      } else {
        errorData = { user_message: detail, severity: 'error' }
      }
    } else if (err.userFriendlyMessage) {
      errorData = { user_message: err.userFriendlyMessage, severity: 'error' }
    } else if (err.message) {
      errorData = { user_message: err.message, severity: 'error' }
    } else {
      errorData = {
        user_message: 'An unexpected error occurred',
        severity: 'error',
        technical_message: String(err)
      }
    }

    setError(errorData)
    return errorData
  }, [])

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  return { error, handleError, clearError }
}

/**
 * Hook for managing retry logic with exponential backoff
 */
export function useRetry(maxRetries = 3, initialDelay = 1000) {
  const [retryCount, setRetryCount] = useState(0)
  const [isRetrying, setIsRetrying] = useState(false)

  const retry = useCallback(async (fn) => {
    if (retryCount >= maxRetries) {
      throw new Error('Maximum retry attempts reached')
    }

    setIsRetrying(true)
    const delay = initialDelay * Math.pow(2, retryCount)

    await new Promise(resolve => setTimeout(resolve, delay))

    try {
      const result = await fn()
      setRetryCount(0)
      setIsRetrying(false)
      return result
    } catch (error) {
      setRetryCount(prev => prev + 1)
      setIsRetrying(false)
      throw error
    }
  }, [retryCount, maxRetries, initialDelay])

  const reset = useCallback(() => {
    setRetryCount(0)
    setIsRetrying(false)
  }, [])

  return { retry, retryCount, isRetrying, reset, canRetry: retryCount < maxRetries }
}
