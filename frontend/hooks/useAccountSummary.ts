'use client'

import { useSharedRealtime } from '@/providers/SharedRealtimeProvider'
import type { AccountSummary } from '@/lib/types'

interface UseAccountSummaryResult {
  summary: AccountSummary | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useAccountSummary(): UseAccountSummaryResult {
  const { accountSummary, lastUpdated, isConnected, refresh } = useSharedRealtime()
  return {
    summary: accountSummary,
    loading: accountSummary === null,
    error: null,
    refetch: () => { refresh('account_summary') },
  }
}
