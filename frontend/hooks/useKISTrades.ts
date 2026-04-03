'use client'

import { useState, useCallback } from 'react'
import type { KISTradeExecution } from '@/lib/kis-types'

interface UseKISTradesResult {
  trades: KISTradeExecution[]
  loading: boolean
  error: string | null
  fetchedAt: string | null
  hasMore: boolean
  refetch: (startDate?: string, endDate?: string) => void
}

function toKISDate(dateStr: string): string {
  return dateStr.replace(/-/g, '')
}

export function useKISTrades(): UseKISTradesResult {
  const [trades, setTrades] = useState<KISTradeExecution[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  const refetch = useCallback(async (startDate?: string, endDate?: string) => {
    setLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams()
      if (startDate) params.set('startDate', toKISDate(startDate))
      if (endDate) params.set('endDate', toKISDate(endDate))

      const resp = await fetch(`/api/kis/trades?${params}`)
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${resp.status}`)
      }
      const result = await resp.json()
      setTrades(result.trades || [])
      setFetchedAt(result.fetchedAt)
      setHasMore(result.hasMore ?? false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'KIS 체결내역 조회 실패')
    }

    setLoading(false)
  }, [])

  return { trades, loading, error, fetchedAt, hasMore, refetch }
}
