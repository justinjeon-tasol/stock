'use client'

import { useState } from 'react'
import { Wallet, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import { useAccountSummary } from '@/hooks/useAccountSummary'
import { useKISBalance } from '@/hooks/useKISBalance'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { formatPrice, formatPct, formatTimeAgo } from '@/lib/format'
import type { KISHolding } from '@/lib/kis-types'

function SummaryRow({
  label,
  value,
  valueClass,
}: {
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#1e1e2a] last:border-0">
      <span className="text-xs text-[#555570]">{label}</span>
      <span className={`text-sm font-semibold ${valueClass ?? 'text-[#f0f0f8]'}`}>{value}</span>
    </div>
  )
}

function HoldingRow({ holding }: { holding: KISHolding }) {
  const isPnlPositive = holding.evluPflsAmt >= 0
  const pnlColor = isPnlPositive ? 'text-[#4ade80]' : 'text-[#f87171]'
  const dayColor = holding.dayChange >= 0 ? 'text-[#4ade80]' : 'text-[#f87171]'

  return (
    <div className="flex items-center gap-3 py-2 border-b border-[#1e1e2a] last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[#f0f0f8] truncate">{holding.name}</span>
          <span className="text-xs text-[#555570]">{holding.code}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-[#555570]">{holding.quantity}주</span>
          <span className="text-xs text-[#555570]">평균 {formatPrice(holding.avgPrice)}</span>
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-sm font-medium text-[#f0f0f8]">{formatPrice(holding.currentPrice)}</div>
        <div className="flex items-center gap-1 justify-end">
          <span className={`text-xs font-medium ${pnlColor}`}>
            {isPnlPositive ? '+' : ''}{formatPct(holding.evluPflsRt)}
          </span>
          <span className={`text-xs ${dayColor}`}>
            ({holding.dayChange >= 0 ? '+' : ''}{formatPct(holding.dayChangeRt)})
          </span>
        </div>
      </div>
    </div>
  )
}

export function AccountSummaryCard() {
  const { summary, loading, error } = useAccountSummary()
  const { data: kisData, loading: kisLoading, refetch: kisRefetch, lastFetchedAt } = useKISBalance()
  const [showHoldings, setShowHoldings] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    await kisRefetch()
    setRefreshing(false)
  }

  if (loading) return <SkeletonCard />
  if (error) {
    return (
      <Card>
        <p className="text-xs text-[#f87171]">데이터 로드 오류: {error}</p>
      </Card>
    )
  }

  if (!summary) {
    return (
      <Card>
        <CardHeader title="계좌 현황" action={<Wallet className="w-4 h-4 text-[#555570]" />} />
        <p className="text-xs text-[#555570] text-center py-4">
          데이터 없음 — 파이프라인 실행 후 표시됩니다
        </p>
      </Card>
    )
  }

  // KIS 실시간 데이터가 있으면 우선 사용
  const displayData = kisData ? {
    totEvluAmt: kisData.summary.totEvluAmt,
    evluPflsAmt: kisData.summary.evluPflsAmt,
    cashAmt: kisData.summary.cashAmt,
    stockEvluAmt: kisData.summary.stockEvluAmt,
    pchsAmt: kisData.summary.pchsAmt,
    updatedAt: lastFetchedAt,
  } : {
    totEvluAmt: summary.tot_evlu_amt,
    evluPflsAmt: summary.evlu_pfls_amt,
    cashAmt: summary.cash_amt,
    stockEvluAmt: summary.stock_evlu_amt,
    pchsAmt: summary.pchs_amt,
    updatedAt: summary.created_at,
  }

  const isPnlPositive = displayData.evluPflsAmt >= 0
  const pnlColor = isPnlPositive ? 'text-[#4ade80]' : 'text-[#f87171]'
  const erngPct = displayData.pchsAmt > 0
    ? (displayData.evluPflsAmt / displayData.pchsAmt) * 100
    : 0

  const holdings = kisData?.holdings ?? []

  return (
    <Card>
      <CardHeader
        title="계좌 현황"
        subtitle={displayData.updatedAt ? formatTimeAgo(displayData.updatedAt) + ' 기준' : undefined}
        action={
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1 rounded hover:bg-[#22222e] transition-colors disabled:opacity-50"
            title="현재가 새로고침"
          >
            <RefreshCw className={`w-4 h-4 text-[#555570] ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        }
      />

      {/* 총 평가금액 강조 */}
      <div className="mb-4">
        <p className="text-xs text-[#555570] mb-0.5">총 평가금액</p>
        <p className="text-2xl font-bold text-[#f0f0f8]">
          {formatPrice(displayData.totEvluAmt)}
        </p>
        <p className={`text-sm font-semibold mt-0.5 ${pnlColor}`}>
          {isPnlPositive ? '+' : ''}{formatPrice(displayData.evluPflsAmt)}&nbsp;
          ({formatPct(erngPct)})
        </p>
      </div>

      {/* 세부 항목 */}
      <div>
        <SummaryRow label="예수금 (현금)" value={formatPrice(displayData.cashAmt)} />
        <SummaryRow label="주식 평가금액" value={formatPrice(displayData.stockEvluAmt)} />
        <SummaryRow label="매수 원가" value={formatPrice(displayData.pchsAmt)} />
        <SummaryRow
          label="평가 손익"
          value={`${isPnlPositive ? '+' : ''}${formatPrice(displayData.evluPflsAmt)}`}
          valueClass={pnlColor}
        />
      </div>

      {/* 보유종목 토글 */}
      {holdings.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[#2a2a38]">
          <button
            onClick={() => setShowHoldings(!showHoldings)}
            className="flex items-center gap-1 w-full text-xs text-[#7c6af7] hover:text-[#9b8cf9] transition-colors"
          >
            {showHoldings ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            보유종목 {holdings.length}개 {showHoldings ? '접기' : '보기'}
          </button>

          {showHoldings && (
            <div className="mt-2">
              {holdings.map((h) => (
                <HoldingRow key={h.code} holding={h} />
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
