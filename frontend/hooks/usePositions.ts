'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '@/lib/supabase'
import type { Position, PositionStatus } from '@/lib/types'

const POLL_INTERVAL_MS = 60_000

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
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const initializedRef = useRef(false)
  const channelId = useRef(`positions_${Date.now()}_${Math.random()}`).current

  const fetchPositions = useCallback(async () => {
    if (!initializedRef.current) setLoading(true)
    setError(null)

    let query = supabase
      .from('positions')
      .select('*')
      .order('entry_time', { ascending: false })

    if (options.status) {
      query = query.eq('status', options.status)
    }

    const { data, error: err } = await query

    if (err) {
      setError(err.message)
      setPositions([])
    } else {
      setPositions((data ?? []) as Position[])
    }

    initializedRef.current = true
    setLoading(false)
  }, [options.status])

  useEffect(() => {
    initializedRef.current = false
    fetchPositions()

    const channel = supabase.channel(`${channelId}_${options.status ?? 'all'}`)
    channel.on('postgres_changes', { event: '*', schema: 'public', table: 'positions' },
      () => { fetchPositions() }
    )
    channel.subscribe()

    timerRef.current = setInterval(fetchPositions, POLL_INTERVAL_MS)

    return () => {
      supabase.removeChannel(channel)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchPositions, options.status, channelId])

  return { positions, loading, error, refetch: fetchPositions }
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
