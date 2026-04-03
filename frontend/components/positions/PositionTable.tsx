'use client'

import { useCallback } from 'react'
import { TrendingUp, TrendingDown, RefreshCw } from 'lucide-react'
import { usePositions } from '@/hooks/usePositions'
import { HorizonBadge } from './HorizonBadge'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { getPhaseToken } from '@/lib/phase-tokens'
import { formatDateTime, formatPrice, formatPct } from '@/lib/format'
import type { PositionStatus } from '@/lib/types'

interface PositionTableProps {
  status: PositionStatus
}

export function PositionTable({ status }: PositionTableProps) {
  const { positions, loading, error, refetch } = usePositions({ status })

  const handleRefresh = useCallback(async () => {
    await refetch()
  }, [refetch])

  if (loading) return <SkeletonTable rows={6} />
  if (error) return <p className="text-xs text-[#f87171] py-4">로드 오류: {error}</p>
  if (positions.length === 0) {
    return (
      <EmptyState
        title={status === 'OPEN' ? '보유 포지션 없음' : '종료된 포지션 없음'}
        description={
          status === 'OPEN'
            ? '현재 매수 중인 종목이 없습니다.'
            : '청산된 포지션 이력이 없습니다.'
        }
      />
    )
  }

  const showCurrentPrice = status === 'OPEN'

  const headers = [
    '종목',
    '수량',
    '평균단가',
    ...(showCurrentPrice ? ['현재가'] : []),
    '투자기간',
    '국면',
    '수익률',
    '진입시각',
    status === 'CLOSED' ? '청산사유' : '최대보유',
  ]

  return (
    <div>
      {/* 새로고침 버튼 (OPEN 탭만) */}
      {showCurrentPrice && (
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-[#555570]">
            Supabase 실시간 동기화 (1분 폴링)
          </span>
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-[#1e1e2a] text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#2a2a38] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            새로고침
          </button>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#2a2a38]">
              {headers.map((h) => (
                <th
                  key={h}
                  className="text-left text-xs text-[#555570] font-medium py-2 px-3 whitespace-nowrap"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const phaseToken = pos.phase_at_buy ? getPhaseToken(pos.phase_at_buy) : null

              const pnl = pos.result_pct ?? null
              const isPositive = (pnl ?? 0) >= 0
              // result_pct에서 현재가 역산
              const curPrice =
                pnl != null && pos.avg_price > 0
                  ? Math.round(pos.avg_price * (1 + pnl / 100))
                  : null

              return (
                <tr
                  key={pos.id}
                  className="border-b border-[#2a2a38] hover:bg-[#1a1a24] transition-colors"
                >
                  {/* 종목 */}
                  <td className="py-3 px-3">
                    <div>
                      <span className="font-medium text-[#f0f0f8]">{pos.name}</span>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-xs text-[#555570]">{pos.code}</span>
                        {pos.mode === 'MOCK' && (
                          <span className="text-xs bg-[#22222e] text-[#555570] px-1 rounded">
                            모의
                          </span>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* 수량 */}
                  <td className="py-3 px-3 text-[#f0f0f8]">
                    {pos.quantity.toLocaleString()}주
                  </td>

                  {/* 평균단가 */}
                  <td className="py-3 px-3 font-mono text-[#f0f0f8]">
                    {formatPrice(pos.avg_price)}
                  </td>

                  {/* 현재가 (OPEN만) */}
                  {showCurrentPrice && (
                    <td className="py-3 px-3 font-mono">
                      {curPrice ? (
                        <span
                          className="font-semibold"
                          style={{ color: isPositive ? '#4ade80' : '#f87171' }}
                        >
                          {formatPrice(curPrice)}
                        </span>
                      ) : (
                        <span className="text-xs text-[#555570]">-</span>
                      )}
                    </td>
                  )}

                  {/* 투자기간 */}
                  <td className="py-3 px-3">
                    <HorizonBadge period={pos.holding_period} />
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
                    {pnl != null ? (
                      <div className="flex items-center gap-1">
                        {isPositive ? (
                          <TrendingUp className="w-3.5 h-3.5 text-[#4ade80]" />
                        ) : (
                          <TrendingDown className="w-3.5 h-3.5 text-[#f87171]" />
                        )}
                        <span
                          className="font-medium"
                          style={{ color: isPositive ? '#4ade80' : '#f87171' }}
                        >
                          {formatPct(pnl)}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-[#888]">갱신대기</span>
                    )}
                  </td>

                  {/* 진입시각 */}
                  <td className="py-3 px-3 text-xs text-[#8888a8] whitespace-nowrap">
                    {formatDateTime(pos.entry_time)}
                  </td>

                  {/* 최대보유 / 청산사유 */}
                  <td className="py-3 px-3">
                    {status === 'OPEN' ? (
                      <span className="text-xs text-[#555570]">
                        {pos.max_exit_date ? formatDateTime(pos.max_exit_date) : '-'}
                      </span>
                    ) : (
                      <span className="text-xs text-[#555570]">
                        {pos.close_reason ?? '-'}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
