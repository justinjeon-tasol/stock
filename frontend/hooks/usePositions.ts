'use client'

import { useMemo } from 'react'
import { useSharedRealtime } from '@/providers/SharedRealtimeProvider'
import type { Position, PositionStatus } from '@/lib/types'

interface UsePositionsOptions {
  status?: PositionStatus
}

interface UsePositionsResult {
  positions: Position[]
  loading: boolean
  error: string | null
  refetch: () => void
}

export function usePositions(options: UsePositionsOptions = {}): UsePositionsResult {
  const { positions: allPositions, lastUpdated, refresh } = useSharedRealtime()

  const positions = useMemo(() => {
    if (!options.status) return allPositions
    return allPositions.filter((p) => p.status === options.status)
  }, [allPositions, options.status])

  return {
    positions,
    loading: allPositions === null,
    error: null,
    refetch: () => { refresh('positions') },
  }
}

// OPEN 포지션 요약 통계
export function usePositionSummary() {
  const { positions, loading, error } = usePositions({ status: 'OPEN' })

  const summary = {
    openCount: positions.length,
    totalValue: positions.reduce((sum, p) => sum + p.avg_price * p.quantity, 0),
    totalPnlPct:
      positions.length > 0
        ? positions.reduce((sum, p) => sum + (p.result_pct ?? 0), 0) / positions.length
        : 0,
    winCount: positions.filter((p) => (p.result_pct ?? 0) >= 0).length,
    loseCount: positions.filter((p) => (p.result_pct ?? 0) < 0).length,
  }

  return { summary, loading, error }
}
