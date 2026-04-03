'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '@/lib/supabase'
import type { MarketPhase } from '@/lib/types'

const POLL_INTERVAL_MS = 60_000

interface UseMarketPhaseResult {
  phase: MarketPhase | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useMarketPhase(): UseMarketPhaseResult {
  const [phase, setPhase] = useState<MarketPhase | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const initializedRef = useRef(false)
  const channelId = useRef(`market_phases_${Date.now()}`).current

  const fetchPhase = useCallback(async () => {
    if (!initializedRef.current) setLoading(true)
    setError(null)

    const { data, error: err } = await supabase
      .from('market_phases')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(1)
      .single()

    if (err) {
      if (err.code !== 'PGRST116') setError(err.message)
      setPhase(null)
    } else {
      setPhase(data as MarketPhase)
    }

    initializedRef.current = true
    setLoading(false)
  }, [])

  useEffect(() => {
    initializedRef.current = false
    fetchPhase()

    const channel = supabase.channel(channelId)
    channel.on('postgres_changes', { event: '*', schema: 'public', table: 'market_phases' },
      () => { fetchPhase() }
    )
    channel.subscribe()

    timerRef.current = setInterval(fetchPhase, POLL_INTERVAL_MS)

    return () => {
      supabase.removeChannel(channel)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchPhase, channelId])

  return { phase, loading, error, refetch: fetchPhase }
}
