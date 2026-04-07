'use client'

import { ArrowUpRight, ArrowDownLeft, Minus } from 'lucide-react'
import { useSharedRealtime } from '@/providers/SharedRealtimeProvider'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { getPhaseToken } from '@/lib/phase-tokens'
import { formatDateTime, formatPrice, formatPct } from '@/lib/format'
import type { Trade } from '@/lib/types'
import Link from 'next/link'

function ActionIcon({ action }: { action: Trade['action'] }) {
  if (action === 'BUY') {
    return <ArrowUpRight className="w-4 h-4 text-[#4ade80]" />
  }
  return <ArrowDownLeft className="w-4 h-4 text-[#f87171]" />
}

export function RecentSignalList() {
  const { recentTrades, lastUpdated } = useSharedRealtime()
  const loading = lastUpdated.trades === null
  const error = null

  const recent = recentTrades.slice(0, 8)

  return (
    <Card>
      <CardHeader
        title="최근 매매 신호"
        subtitle="최근 8건"
        action={
          <Link
            href="/trades"
            className="text-xs text-[#7c6af7] hover:text-[#9b8cf9] transition-colors"
          >
            전체 보기
          </Link>
        }
      />

      {loading && <SkeletonTable rows={4} />}
      {error && <p className="text-xs text-[#f87171]">로드 오류: {error}</p>}

      {!loading && !error && recent.length === 0 && (
        <EmptyState title="신호 없음" description="매매 이력이 없습니다." />
      )}

      {!loading && !error && recent.length > 0 && (
        <div className="space-y-0">
          {recent.map((trade) => {
            const phaseToken = trade.phase ? getPhaseToken(trade.phase) : null
            const isProfit = (trade.result_pct ?? 0) >= 0

            return (
              <div
                key={trade.id}
                className="flex items-center gap-3 py-2.5 border-b border-[#2a2a38] last:border-0"
              >
                <ActionIcon action={trade.action} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#f0f0f8] truncate">
                      {trade.name}
                    </span>
                    <span className="text-xs text-[#555570]">{trade.code}</span>
                    {trade.mode === 'MOCK' && (
                      <span className="text-xs bg-[#22222e] text-[#555570] px-1.5 py-0.5 rounded">
                        모의
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-[#555570]">
                      {formatDateTime(trade.created_at)}
                    </span>
                    {phaseToken && (
                      <span
                        className="text-xs px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: phaseToken.bg, color: phaseToken.text }}
                      >
                        {phaseToken.label}
                      </span>
                    )}
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="text-sm font-medium text-[#f0f0f8]">
                    {formatPrice(trade.price)}
                  </div>
                  {trade.result_pct !== null && (
                    <div
                      className="text-xs font-medium"
                      style={{ color: isProfit ? '#4ade80' : '#f87171' }}
                    >
                      {formatPct(trade.result_pct)}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
