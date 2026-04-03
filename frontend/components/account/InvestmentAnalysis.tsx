'use client'

import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'
import { useInvestmentAnalysis } from '@/hooks/useInvestmentAnalysis'
import { useKISTrades } from '@/hooks/useKISTrades'
import { EquityCurveChart } from './EquityCurveChart'
import { MonthlyReturnChart } from './MonthlyReturnChart'
import { StockPerformanceTable } from './StockPerformanceTable'
import { WinLossStats } from './WinLossStats'
import type { Trade } from '@/lib/types'
import type { KISAccountSummary } from '@/lib/kis-types'

interface InvestmentAnalysisProps {
  kisSummary?: KISAccountSummary | null
}

export function InvestmentAnalysis({ kisSummary }: InvestmentAnalysisProps) {
  const [trades, setTrades] = useState<Trade[]>([])
  const [equityData, setEquityData] = useState<{ date: string; value: number }[]>([])
  const [loading, setLoading] = useState(true)
  const [syncWarning, setSyncWarning] = useState<string | null>(null)

  // KIS 거래내역 (대조용)
  const { trades: kisTrades, refetch: refetchKIS } = useKISTrades()

  // KIS 최근 30일 거래내역 조회
  useEffect(() => {
    const end = new Date()
    const start = new Date(end.getTime() - 30 * 86400000)
    refetchKIS(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10))
  }, [refetchKIS])

  // Supabase에서 전체 거래 이력 + 계좌 이력 로드
  useEffect(() => {
    async function load() {
      setLoading(true)

      const [tradesRes, historyRes] = await Promise.all([
        supabase
          .from('trades')
          .select('*')
          .order('created_at', { ascending: true }),
        supabase
          .from('account_history')
          .select('recorded_date, tot_evlu_amt')
          .order('recorded_date', { ascending: true }),
      ])

      setTrades((tradesRes.data as Trade[]) || [])

      // 자산 추이 데이터
      const histPoints = (historyRes.data || []).map((h: { recorded_date: string; tot_evlu_amt: number }) => ({
        date: h.recorded_date.slice(5), // "MM-DD"
        value: h.tot_evlu_amt,
      }))

      // KIS 현재 잔고를 최신 포인트로 추가
      if (kisSummary && kisSummary.totEvluAmt > 0) {
        const today = new Date().toISOString().slice(5, 10) // "MM-DD"
        const last = histPoints[histPoints.length - 1]
        if (!last || last.date !== today) {
          histPoints.push({ date: today, value: kisSummary.totEvluAmt })
        } else {
          last.value = kisSummary.totEvluAmt
        }
      }

      setEquityData(histPoints)
      setLoading(false)
    }

    load()
  }, [kisSummary])

  // KIS ↔ Supabase 거래 대조
  useEffect(() => {
    if (kisTrades.length === 0 || trades.length === 0) {
      setSyncWarning(null)
      return
    }

    // KIS 체결 완료된 거래의 주문번호 집합
    const kisOrderNos = new Set(
      kisTrades
        .filter(t => t.filledQty > 0)
        .map(t => t.orderNo)
    )

    // Supabase trades의 order_id 집합
    const sbOrderIds = new Set(
      trades
        .filter(t => t.order_id)
        .map(t => t.order_id!)
    )

    // KIS에는 있지만 Supabase에 없는 거래 감지
    const missingInSB = Array.from(kisOrderNos).filter(no => !sbOrderIds.has(no))

    if (missingInSB.length > 0) {
      setSyncWarning(
        `KIS 체결내역 중 ${missingInSB.length}건이 DB에 기록되지 않았습니다. (주문번호: ${missingInSB.slice(0, 3).join(', ')}${missingInSB.length > 3 ? ' ...' : ''})`
      )
    } else {
      setSyncWarning(null)
    }
  }, [kisTrades, trades])

  const { monthlyReturns, stockReturns, stats, totalTradesIncludingBuy } = useInvestmentAnalysis({ trades })

  if (loading) {
    return (
      <div className="text-center py-12 text-[#555570] text-sm">
        분석 데이터 로딩 중...
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 데이터 동기화 경고 */}
      {syncWarning && (
        <div className="text-xs text-yellow-400 bg-yellow-400/10 px-3 py-2 rounded">
          {syncWarning}
        </div>
      )}

      {/* 전체 거래 건수 안내 */}
      {totalTradesIncludingBuy > stats.totalTrades && (
        <div className="text-xs text-[#555570]">
          전체 {totalTradesIncludingBuy}건 중 매도 청산 {stats.totalTrades}건 기준 분석 (매수 전용 거래는 실현 손익 없음)
        </div>
      )}

      {/* 매매 통계 */}
      <WinLossStats stats={stats} />

      {/* 차트 2열 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EquityCurveChart data={equityData} />
        <MonthlyReturnChart data={monthlyReturns} />
      </div>

      {/* 종목별 손익 */}
      <StockPerformanceTable data={stockReturns} />
    </div>
  )
}
