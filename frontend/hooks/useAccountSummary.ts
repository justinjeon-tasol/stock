'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '@/lib/supabase'
import type { AccountSummary } from '@/lib/types'

const POLL_INTERVAL_MS = 60_000 // 1분 폴링 (실시간 구독 백업)

interface UseAccountSummaryResult {
  summary: AccountSummary | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useAccountSummary(): UseAccountSummaryResult {
  const [summary, setSummary] = useState<AccountSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const initializedRef = useRef(false)
  const channelId = useRef(`account_summary_${Date.now()}`).current

  const fetchSummary = useCallback(async () => {
    if (!initializedRef.current) setLoading(true)
    setError(null)

    const { data, error: err } = await supabase
      .from('account_summary')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(1)
      .single()

    if (err) {
      if (err.code === 'PGRST116') {
        setSummary(null)
      } else {
        setError(err.message)
      }
    } else {
      setSummary(data as AccountSummary)
    }

    initializedRef.current = true
    setLoading(false)
  }, [])

  useEffect(() => {
    initializedRef.current = false
    fetchSummary()

    const channel = supabase.channel(channelId)
    channel.on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'account_summary' },
      (payload) => { setSummary(payload.new as AccountSummary) }
    )
    channel.subscribe()

    timerRef.current = setInterval(fetchSummary, POLL_INTERVAL_MS)

    return () => {
      supabase.removeChannel(channel)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchSummary, channelId])

  return { summary, loading, error, refetch: fetchSummary }
}
