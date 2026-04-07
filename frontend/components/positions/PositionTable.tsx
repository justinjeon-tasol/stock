'use client'

import { useCallback, useState, useMemo } from 'react'
import { TrendingUp, TrendingDown, RefreshCw, ArrowUp, ArrowDown, Minus } from 'lucide-react'
import { usePositions } from '@/hooks/usePositions'
import { HorizonBadge } from './HorizonBadge'
import { SignalBadge } from '@/components/ui/SignalBadge'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { getPhaseToken } from '@/lib/phase-tokens'
import { formatDateTime, formatPrice, formatPct } from '@/lib/format'
import type { Position, PositionStatus, HoldingPeriod } from '@/lib/types'
import type { KISPrice } from '@/lib/kis-types'

interface PositionTableProps {
  status: PositionStatus
  grouped?: boolean
}

const HORIZON_ORDER: HoldingPeriod[] = ['장기', '중기', '단기', '초단기']

const HORIZON_LABELS: Record<HoldingPeriod, string> = {
  장기: '장기 보유 (1~3개월)',
  중기: '중기 보유 (1~4주)',
  단기: '단기 보유 (1~5일)',
  초단기: '당일 청산 (장중)',
}

function KalmanBadge({ trend }: { trend: string | null }) {
  if (!trend) return <span className="text-xs text-[#555570]">-</span>

  if (trend === 'UP') {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-[#052e16] text-[#4ade80] border border-[#4ade80]/30">
        <ArrowUp className="w-3 h-3" />상승
      </span>
    )
  }
  if (trend === 'DOWN') {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-[#450a0a] text-[#f87171] border border-[#f87171]/30">
        <ArrowDown className="w-3 h-3" />하락
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-[#1e1e2a] text-[#8888a8] border border-[#555570]/30">
      <Minus className="w-3 h-3" />횡보
    </span>
  )
}

export function PositionTable({ status, grouped = false }: PositionTableProps) {
  const { positions, loading, error, refetch } = usePositions({ status })
  const [livePrice, setLivePrice] = useState<Record<string, KISPrice>>({})
  const [kalmanTrends, setKalmanTrends] = useState<Record<string, string>>({})
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    await refetch()

    // OPEN 포지션의 현재가 + 칼만 추세 조회
    if (status === 'OPEN') {
      const openPositions = positions.filter(p => p.status === 'OPEN')
      const pricePromises = openPositions.map(async (pos) => {
        try {
          const resp = await fetch(`/api/kis/price?code=${pos.code}`)
          if (resp.ok) {
            const data: KISPrice = await resp.json()
            return { code: pos.code, data }
          }
        } catch { /* ignore */ }
        return null
      })

      const kalmanResp = await fetch('/api/kalman-trends').catch(() => null)
      if (kalmanResp?.ok) {
        const trends = await kalmanResp.json()
        setKalmanTrends(trends)
      }

      const results = await Promise.all(pricePromises)
      const priceMap: Record<string, KISPrice> = {}
      for (const r of results) {
        if (r) priceMap[r.code] = r.data
      }
      setLivePrice(priceMap)
    }

    setRefreshing(false)
  }, [refetch, positions, status])

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

  // 그룹핑
  const groupedPositions = useMemo(() => {
    if (!grouped) return null
    const groups: Record<string, Position[]> = {}
    for (const hp of HORIZON_ORDER) {
      groups[hp] = []
    }
    for (const pos of positions) {
      const hp = pos.holding_period || '단기'
      if (!groups[hp]) groups[hp] = []
      groups[hp].push(pos)
    }
    return groups
  }, [positions, grouped])

  const renderRow = (pos: Position) => {
    const phaseToken = pos.phase_at_buy ? getPhaseToken(pos.phase_at_buy) : null
    const pnl = pos.result_pct ?? null
    const live = livePrice[pos.code]
    const curPrice = live ? live.price : (
      pnl != null && pos.avg_price > 0
        ? Math.round(pos.avg_price * (1 + pnl / 100))
        : null
    )
    const livePnl = live && pos.avg_price > 0
      ? ((live.price - pos.avg_price) / pos.avg_price) * 100
      : pnl
    const isPositive = (livePnl ?? 0) >= 0
    const kalman = kalmanTrends[pos.code] ?? null

    return (
      <tr
        key={pos.id}
        className="border-b border-[#2a2a38] hover:bg-[#1a1a24] transition-colors"
      >
        <td className="py-3 px-3">
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-[#f0f0f8]">{pos.name}</span>
              <SignalBadge
                source={pos.signal_source}
                confidence={pos.signal_confidence}
                trigger={pos.signal_trigger}
              />
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs text-[#555570]">{pos.code}</span>
              {pos.mode === 'MOCK' && (
                <span className="text-xs bg-[#22222e] text-[#555570] px-1 rounded">모의</span>
              )}
            </div>
          </div>
        </td>
        <td className="py-3 px-3 text-[#f0f0f8]">{pos.quantity.toLocaleString()}주</td>
        <td className="py-3 px-3 font-mono text-[#f0f0f8]">{formatPrice(pos.avg_price)}</td>
        {showCurrentPrice && (
          <td className="py-3 px-3 font-mono">
            {curPrice ? (
              <div>
                <span className="font-semibold" style={{ color: isPositive ? '#4ade80' : '#f87171' }}>
                  {formatPrice(curPrice)}
                </span>
                {live && (
                  <div className="text-xs mt-0.5" style={{ color: live.dayChange >= 0 ? '#4ade80' : '#f87171' }}>
                    {live.dayChange >= 0 ? '+' : ''}{formatPct(live.dayChangeRt)}
                  </div>
                )}
              </div>
            ) : (
              <span className="text-xs text-[#555570]">-</span>
            )}
          </td>
        )}
        {!grouped && (
          <td className="py-3 px-3">
            <HorizonBadge period={pos.holding_period} />
          </td>
        )}
        {showCurrentPrice && (
          <td className="py-3 px-3">
            <KalmanBadge trend={kalman} />
          </td>
        )}
        <td className="py-3 px-3">
          {phaseToken ? (
            <span
              className="text-xs px-2 py-0.5 rounded-full border"
              style={{ backgroundColor: phaseToken.bg, color: phaseToken.text, borderColor: phaseToken.border }}
            >
              {phaseToken.label}
            </span>
          ) : (
            <span className="text-xs text-[#555570]">-</span>
          )}
        </td>
        <td className="py-3 px-3">
          {livePnl != null ? (
            <div className="flex items-center gap-1">
              {isPositive ? (
                <TrendingUp className="w-3.5 h-3.5 text-[#4ade80]" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 text-[#f87171]" />
              )}
              <span className="font-medium" style={{ color: isPositive ? '#4ade80' : '#f87171' }}>
                {formatPct(livePnl)}
              </span>
            </div>
          ) : (
            <span className="text-xs text-[#888]">갱신대기</span>
          )}
        </td>
        <td className="py-3 px-3 text-xs text-[#8888a8] whitespace-nowrap">
          {formatDateTime(pos.entry_time)}
        </td>
        <td className="py-3 px-3">
          {status === 'OPEN' ? (
            <span className="text-xs text-[#555570]">
              {pos.max_exit_date ? formatDateTime(pos.max_exit_date) : '-'}
            </span>
          ) : (
            <span className="text-xs text-[#555570]">{pos.close_reason ?? '-'}</span>
          )}
        </td>
      </tr>
    )
  }

  const headers = [
    '종목',
    '수량',
    '평균단가',
    ...(showCurrentPrice ? ['현재가'] : []),
    ...(!grouped ? ['투자기간'] : []),
    ...(showCurrentPrice ? ['칼만추세'] : []),
    '국면',
    '수익률',
    '진입시각',
    status === 'CLOSED' ? '청산사유' : '최대보유',
  ]

  return (
    <div>
      {showCurrentPrice && (
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-[#555570]">
            {Object.keys(livePrice).length > 0
              ? `KIS 현재가 조회됨 (${Object.keys(livePrice).length}종목)`
              : 'Supabase 실시간 동기화'}
          </span>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-[#1e1e2a] text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#2a2a38] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
            현재가 조회
          </button>
        </div>
      )}

      {grouped && groupedPositions ? (
        // 보유기간별 그룹 뷰
        <div className="space-y-4">
          {HORIZON_ORDER.map((hp) => {
            const group = groupedPositions[hp]
            if (!group || group.length === 0) return null

            return (
              <div key={hp}>
                <div className="flex items-center gap-2 mb-2 px-1">
                  <HorizonBadge period={hp} />
                  <span className="text-xs text-[#8888a8]">
                    {HORIZON_LABELS[hp]} — {group.length}종목
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#2a2a38]">
                        {headers.map((h) => (
                          <th key={h} className="text-left text-xs text-[#555570] font-medium py-2 px-3 whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>{group.map(renderRow)}</tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        // 기존 플랫 뷰
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2a38]">
                {headers.map((h) => (
                  <th key={h} className="text-left text-xs text-[#555570] font-medium py-2 px-3 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>{positions.map(renderRow)}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}
