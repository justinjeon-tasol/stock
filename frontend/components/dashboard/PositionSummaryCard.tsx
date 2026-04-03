'use client'

import { Briefcase, TrendingUp, TrendingDown } from 'lucide-react'
import { usePositionSummary } from '@/hooks/usePositions'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { formatAmount, formatPct } from '@/lib/format'

export function PositionSummaryCard() {
  const { summary, loading, error } = usePositionSummary()

  if (loading) return <SkeletonCard />
  if (error) {
    return (
      <Card>
        <p className="text-xs text-[#f87171]">데이터 로드 오류: {error}</p>
      </Card>
    )
  }

  const isPositive = summary.totalPnlPct >= 0

  return (
    <Card>
      <CardHeader
        title="포지션 요약"
        subtitle={`OPEN ${summary.openCount}건`}
        action={
          <Briefcase className="w-4 h-4 text-[#555570]" />
        }
      />

      <div className="grid grid-cols-2 gap-4">
        {/* 보유 종목 수 */}
        <div>
          <p className="text-xs text-[#555570] mb-1">보유 종목</p>
          <p className="text-2xl font-bold text-[#f0f0f8]">
            {summary.openCount}
            <span className="text-sm font-normal text-[#8888a8] ml-1">종목</span>
          </p>
        </div>

        {/* 평균 수익률 */}
        <div>
          <p className="text-xs text-[#555570] mb-1">평균 수익률</p>
          <p
            className="text-2xl font-bold"
            style={{ color: isPositive ? '#4ade80' : '#f87171' }}
          >
            {summary.openCount > 0 ? formatPct(summary.totalPnlPct) : '-'}
          </p>
        </div>

        {/* 총 평가액 */}
        <div>
          <p className="text-xs text-[#555570] mb-1">총 평가액</p>
          <p className="text-sm font-semibold text-[#f0f0f8]">
            {summary.openCount > 0 ? formatAmount(summary.totalValue) : '-'}
          </p>
        </div>

        {/* 승/패 */}
        <div>
          <p className="text-xs text-[#555570] mb-1">수익/손실</p>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-0.5 text-sm text-[#4ade80]">
              <TrendingUp className="w-3.5 h-3.5" />
              {summary.winCount}
            </span>
            <span className="text-[#3a3a4e]">/</span>
            <span className="flex items-center gap-0.5 text-sm text-[#f87171]">
              <TrendingDown className="w-3.5 h-3.5" />
              {summary.loseCount}
            </span>
          </div>
        </div>
      </div>
    </Card>
  )
}
