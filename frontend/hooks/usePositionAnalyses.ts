'use client'

import { useState, useEffect, useCallback } from 'react'
import { supabase } from '@/lib/supabase'
import type { PositionAnalysis } from '@/lib/types'

interface UsePositionAnalysesResult {
  analyses: Record<string, PositionAnalysis>  // position_id → 최신 분석
  loading: boolean
  error: string | null
  refetch: () => void
}

export function usePositionAnalyses(): UsePositionAnalysesResult {
  const [analyses, setAnalyses] = useState<Record<string, PositionAnalysis>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAnalyses = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      // OPEN 포지션 id 목록 조회
      const { data: positions, error: posErr } = await supabase
        .from('positions')
        .select('id')
        .eq('status', 'OPEN')

      if (posErr) {
        setError(posErr.message)
        setLoading(false)
        return
      }

      if (!positions || positions.length === 0) {
        setAnalyses({})
        setLoading(false)
        return
      }

      const positionIds = positions.map((p) => p.id)

      // position_analyses에서 해당 포지션들의 분석 결과 조회 (최신순)
      const { data, error: anaErr } = await supabase
        .from('position_analyses')
        .select('*')
        .in('position_id', positionIds)
        .order('created_at', { ascending: false })

      if (anaErr) {
        setError(anaErr.message)
        setLoading(false)
        return
      }

      // position_id별 최신 1건만 추출
      const result: Record<string, PositionAnalysis> = {}
      for (const row of (data ?? []) as PositionAnalysis[]) {
        if (row.position_id && !result[row.position_id]) {
          result[row.position_id] = row
        }
      }

      setAnalyses(result)
    } catch (err) {
      // position_analyses 테이블이 없는 경우 등 예외 처리
      const msg = err instanceof Error ? err.message : '알 수 없는 오류'
      setError(msg)
    }

    setLoading(false)
  }, [])

  useEffect(() => {
    fetchAnalyses()
  }, [fetchAnalyses])

  return { analyses, loading, error, refetch: fetchAnalyses }
}
