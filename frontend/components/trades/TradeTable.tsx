'use client'

import { ArrowUpRight, ArrowDownLeft } from 'lucide-react'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { getPhaseToken } from '@/lib/phase-tokens'
import { formatDateTime, formatPrice, formatPct } from '@/lib/format'
import type { Trade } from '@/lib/types'

interface TradeTableProps {
  trades: Trade[]
  loading: boolean
  error: string | null
}

export function TradeTable({ trades, loading, error }: TradeTableProps) {
  if (loading) return <SkeletonTable rows={8} />
  if (error) return <p className="text-xs text-[#f87171] py-4">로드 오류: {error}</p>
  if (trades.length === 0) {
    return <EmptyState title="매매 이력 없음" description="필터 조건에 맞는 거래가 없습니다." />
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#2a2a38]">
            {['일시', '구분', '종목', '수량', '가격', '전략', '국면', '수익률', '모드'].map(
              (h) => (
                <th
                  key={h}
                  className="text-left text-xs text-[#555570] font-medium py-2 px-3 whitespace-nowrap"
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const phaseToken = trade.phase ? getPhaseToken(trade.phase) : null
            const isBuy = trade.action === 'BUY'
            const pnl = trade.result_pct ?? null
            const isProfit = pnl !== null && pnl >= 0

            return (
              <tr
                key={trade.id}
                className="border-b border-[#2a2a38] hover:bg-[#1a1a24] transition-colors"
              >
                {/* 일시 */}
                <td className="py-3 px-3 text-xs text-[#8888a8] whitespace-nowrap">
                  {formatDateTime(trade.created_at)}
                </td>

                {/* 구분 */}
                <td className="py-3 px-3">
                  <span
                    className="flex items-center gap-1 text-xs font-medium w-fit"
                    style={{ color: isBuy ? '#4ade80' : '#f87171' }}
                  >
                    {isBuy ? (
                      <ArrowUpRight className="w-3.5 h-3.5" />
                    ) : (
                      <ArrowDownLeft className="w-3.5 h-3.5" />
                    )}
                    {isBuy ? '매수' : '매도'}
                  </span>
                </td>

                {/* 종목 */}
                <td className="py-3 px-3">
                  <div>
                    <span className="font-medium text-[#f0f0f8]">{trade.name}</span>
                    <div className="text-xs text-[#555570]">{trade.code}</div>
                  </div>
                </td>

                {/* 수량 */}
                <td className="py-3 px-3 text-[#f0f0f8]">
                  {trade.quantity.toLocaleString()}주
                </td>

                {/* 가격 */}
                <td className="py-3 px-3 font-mono text-[#f0f0f8] whitespace-nowrap">
                  {formatPrice(trade.price)}
                </td>

                {/* 전략 */}
                <td className="py-3 px-3">
                  <span className="text-xs text-[#555570] font-mono">
                    {trade.strategy_id ?? '-'}
                  </span>
                </td>

                {/* 국면 */}
                <td className="py-3 px-3">
                  {phaseToken ? (
                    <span
                      className="text-xs px-2 py-0.5 rounded-full border"
                      style={{
                        backgroundColor: phaseToken.bg,
                        color: phaseToken.text,
                        borderColor: phaseToken.border,
                      }}
                    >
                      {phaseToken.label}
                    </span>
                  ) : (
                    <span className="text-xs text-[#555570]">-</span>
                  )}
                </td>

                {/* 수익률 */}
                <td className="py-3 px-3">
                  {pnl !== null ? (
                    <span
                      className="text-xs font-medium"
                      style={{ color: isProfit ? '#4ade80' : '#f87171' }}
                    >
                      {formatPct(pnl)}
                    </span>
                  ) : (
                    <span className="text-xs text-[#555570]">-</span>
                  )}
                </td>

                {/* 모드 */}
                <td className="py-3 px-3">
                  <span
                    className="text-xs px-1.5 py-0.5 rounded"
                    style={{
                      backgroundColor:
                        trade.mode === 'REAL' ? '#064e3b' : '#22222e',
                      color: trade.mode === 'REAL' ? '#34d399' : '#555570',
                    }}
                  >
                    {trade.mode === 'REAL' ? '실전' : '모의'}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
