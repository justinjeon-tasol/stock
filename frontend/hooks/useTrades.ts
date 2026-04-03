'use client'

import { useState, useEffect, useCallback } from 'react'
import { supabase } from '@/lib/supabase'
import type { Trade, TradeFilter } from '@/lib/types'

interface UseTradesResult {
  trades: Trade[]
  loading: boolean
  error: string | null
  refetch: () => void
}

const DEFAULT_FILTER: TradeFilter = {
  action: 'ALL',
  mode: 'ALL',
  phase: 'ALL',
  dateFrom: '',
  dateTo: '',
}

export function useTrades(filter: TradeFilter = DEFAULT_FILTER): UseTradesResult {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchTrades = useCallback(async () => {
    setLoading(true)
    setError(null)

    let query = supabase
      .from('trades')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(200)

    if (filter.action !== 'ALL') {
      query = query.eq('action', filter.action)
    }
    if (filter.mode !== 'ALL') {
      query = query.eq('mode', filter.mode)
    }
    if (filter.phase !== 'ALL') {
      query = query.eq('phase', filter.phase)
    }
    if (filter.dateFrom) {
      query = query.gte('created_at', filter.dateFrom)
    }
    if (filter.dateTo) {
      query = query.lte('created_at', filter.dateTo + 'T23:59:59')
    }

    const { data, error: err } = await query

    if (err) {
      setError(err.message)
      setTrades([])
    } else {
      setTrades((data ?? []) as Trade[])
    }

    setLoading(false)
  }, [filter.action, filter.mode, filter.phase, filter.dateFrom, filter.dateTo])

  useEffect(() => {
    fetchTrades()
  }, [fetchTrades])

  return { trades, loading, error, refetch: fetchTrades }
}
