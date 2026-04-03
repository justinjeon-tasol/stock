'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import type { KISBalanceResponse } from '@/lib/kis-types'

const POLL_INTERVAL_MS = 30_000 // 30초 폴링

interface UseKISBalanceResult {
  data: KISBalanceResponse | null
  loading: boolean
  error: string | null
  lastFetchedAt: string | null
  refetch: () => void
}

export function useKISBalance(): UseKISBalanceResult {
  const [data, setData] = useState<KISBalanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const initialRef = useRef(false)

  const fetchData = useCallback(async () => {
    if (!initialRef.current) setLoading(true)
    setError(null)

    try {
      const resp = await fetch('/api/kis/balance')
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${resp.status}`)
      }
      const result: KISBalanceResponse = await resp.json()
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'KIS 잔고 조회 실패')
    }

    initialRef.current = true
    setLoading(false)
  }, [])

  useEffect(() => {
    initialRef.current = false
    fetchData()
    timerRef.current = setInterval(fetchData, POLL_INTERVAL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchData])

  return {
    data,
    loading,
    error,
    lastFetchedAt: data?.fetchedAt ?? null,
    refetch: fetchData,
  }
}
