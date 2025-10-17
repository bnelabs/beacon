/**
 * Custom hook for conditional auto-refetch based on active jobs/processes
 * Prevents unnecessary refreshing when nothing is running
 */

import { useState, useEffect } from 'react'

/**
 * Hook to determine if auto-refetch should be enabled based on active jobs
 * @param {Array} items - Array of items to check (jobs, pipelines, etc.)
 * @param {Function} isActiveCheck - Function to determine if item is active (e.g., status === 'running')
 * @param {number} activeInterval - Refresh interval when active (ms)
 * @param {number|false} inactiveInterval - Refresh interval when inactive (ms) or false to disable
 * @returns {number|false} - Current refetch interval
 */
export function useConditionalRefetch(items, isActiveCheck, activeInterval = 3000, inactiveInterval = 30000) {
  const [refetchInterval, setRefetchInterval] = useState(inactiveInterval)

  useEffect(() => {
    if (!items || items.length === 0) {
      setRefetchInterval(inactiveInterval)
      return
    }

    const hasActiveItems = items.some(isActiveCheck)

    if (hasActiveItems) {
      setRefetchInterval(activeInterval)
    } else {
      setRefetchInterval(inactiveInterval)
    }
  }, [items, isActiveCheck, activeInterval, inactiveInterval])

  return refetchInterval
}

/**
 * Hook specifically for job status checking
 * @param {Array} jobs - Array of job objects
 * @param {number} activeInterval - Refresh interval when jobs running (default: 2s)
 * @param {number|false} inactiveInterval - Refresh interval when no jobs (default: 30s)
 */
export function useJobRefetch(jobs, activeInterval = 2000, inactiveInterval = 30000) {
  return useConditionalRefetch(
    jobs,
    (job) => job.status === 'running' || job.status === 'pending',
    activeInterval,
    inactiveInterval
  )
}

/**
 * Hook specifically for pipeline status checking
 * @param {Array} pipelines - Array of pipeline objects
 * @param {number} activeInterval - Refresh interval when pipelines running (default: 3s)
 * @param {number|false} inactiveInterval - Refresh interval when no pipelines (default: false = disabled)
 */
export function usePipelineRefetch(pipelines, activeInterval = 3000, inactiveInterval = false) {
  return useConditionalRefetch(
    pipelines,
    (pipeline) => pipeline.status === 'running' || pipeline.status === 'pending',
    activeInterval,
    inactiveInterval
  )
}
