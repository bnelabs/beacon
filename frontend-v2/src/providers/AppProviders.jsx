import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

const createClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: 2
      }
    }
  })

export function AppProviders({ children }) {
  const [client] = useState(() => createClient())

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
