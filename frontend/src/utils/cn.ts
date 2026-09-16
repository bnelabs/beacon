import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Conditional className composer: `clsx` for the conditional joining, then
 * `tailwind-merge` so later Tailwind utilities win over earlier conflicting
 * ones (e.g. `cn('p-2', cond && 'p-4')` -> `p-4`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(...inputs))
}
