'use client'

import { useMemo } from 'react'
import type { Trade } from '@/lib/types'
import type {
  PeriodReturn,
  StockReturn,
  WinLossStatsData,
} from '@/lib/kis-types'

interface AnalysisInput {
  trades: Trade[]
}

interface AnalysisResult {
  monthlyReturns: PeriodReturn[]
  stockReturns: StockReturn[]
  stats: WinLossStatsData
  totalTradesIncludingBuy: number
}

export function useInvestmentAnalysis({ trades }: AnalysisInput): AnalysisResult {
  return useMemo(() => {
    // 실현 손익이 있는 SELL 거래 (분석 대상)
    const sellTradesWithPnl = trades.filter(t => t.action === 'SELL' && t.result_pct != null)
    // result_pct가 null인 거래 (BUY 거래 또는 아직 미청산)
    const tradesWithoutPnl = trades.filter(t => t.result_pct == null)

    // ─── 월별 수익률 ───
    const monthMap = new Map<string, { returns: number[]; count: number; wins: number }>()
    for (const t of sellTradesWithPnl) {
      const month = t.created_at.slice(0, 7) // "YYYY-MM"
      const entry = monthMap.get(month) || { returns: [], count: 0, wins: 0 }
      entry.returns.push(t.result_pct!)
      entry.count++
      if (t.result_pct! > 0) entry.wins++
      monthMap.set(month, entry)
    }

    const monthlyReturns: PeriodReturn[] = Array.from(monthMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, data]) => ({
        period,
        returnPct: data.returns.reduce((sum, r) => sum + r, 0) / data.returns.length,
        tradeCount: data.count,
        winCount: data.wins,
      }))

    // ─── 종목별 손익 ───
    const stockMap = new Map<string, { name: string; pnls: number[]; count: number; wins: number }>()
    for (const t of sellTradesWithPnl) {
      const entry = stockMap.get(t.code) || { name: t.name, pnls: [], count: 0, wins: 0 }
      entry.pnls.push(t.result_pct!)
      entry.count++
      if (t.result_pct! > 0) entry.wins++
      stockMap.set(t.code, entry)
    }

    const stockReturns: StockReturn[] = Array.from(stockMap.entries())
      .map(([code, data]) => ({
        code,
        name: data.name,
        totalPnl: data.pnls.reduce((sum, r) => sum + r, 0),
        totalPnlPct: data.pnls.reduce((sum, r) => sum + r, 0) / data.pnls.length,
        tradeCount: data.count,
        winCount: data.wins,
        winRate: data.count > 0 ? (data.wins / data.count) * 100 : 0,
      }))
      .sort((a, b) => b.totalPnl - a.totalPnl)

    // ─── 통계 ───
    const wins = sellTradesWithPnl.filter(t => t.result_pct! > 0)
    const losses = sellTradesWithPnl.filter(t => t.result_pct! <= 0)
    const avgWin = wins.length > 0
      ? wins.reduce((s, t) => s + t.result_pct!, 0) / wins.length
      : 0
    const avgLoss = losses.length > 0
      ? losses.reduce((s, t) => s + t.result_pct!, 0) / losses.length
      : 0
    const grossWin = wins.reduce((s, t) => s + t.result_pct!, 0)
    const grossLoss = Math.abs(losses.reduce((s, t) => s + t.result_pct!, 0))

    // 연승/연패
    let maxConsWins = 0, maxConsLosses = 0, curWins = 0, curLosses = 0
    for (const t of sellTradesWithPnl) {
      if (t.result_pct! > 0) {
        curWins++
        curLosses = 0
        maxConsWins = Math.max(maxConsWins, curWins)
      } else {
        curLosses++
        curWins = 0
        maxConsLosses = Math.max(maxConsLosses, curLosses)
      }
    }

    const stats: WinLossStatsData = {
      totalTrades: sellTradesWithPnl.length,
      winRate: sellTradesWithPnl.length > 0 ? (wins.length / sellTradesWithPnl.length) * 100 : 0,
      avgWinPct: avgWin,
      avgLossPct: avgLoss,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0,
      maxConsecutiveWins: maxConsWins,
      maxConsecutiveLosses: maxConsLosses,
      totalRealizedPnl: sellTradesWithPnl.reduce((s, t) => s + t.result_pct!, 0),
    }

    return {
      monthlyReturns,
      stockReturns,
      stats,
      totalTradesIncludingBuy: trades.length,
    }
  }, [trades])
}
