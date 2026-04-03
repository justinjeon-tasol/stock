'use client'

import { useSharedRealtime } from '@/providers/SharedRealtimeProvider'
import type { MarketPhase } from '@/lib/types'

interface UseMarketPhaseResult {
  phase: MarketPhase | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useMarketPhase(): UseMarketPhaseResult {
  const { marketPhase, lastUpdated, isConnected, refresh } = useSharedRealtime()
  return {
    phase: marketPhase,
    loading: marketPhase === null,
    error: null,
    refetch: () => { refresh('market_phases') },
  }
}
