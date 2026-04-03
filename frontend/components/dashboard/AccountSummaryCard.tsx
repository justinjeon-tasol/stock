'use client'

import { Wallet } from 'lucide-react'
import { useAccountSummary } from '@/hooks/useAccountSummary'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { formatPrice, formatPct, formatTimeAgo } from '@/lib/format'

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

export function AccountSummaryCard() {
  const { summary, loading, error } = useAccountSummary()

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

  const isPnlPositive = summary.evlu_pfls_amt >= 0
  const pnlColor = isPnlPositive ? 'text-[#4ade80]' : 'text-[#f87171]'
  // 수익률 = 평가손익 / 매수원가 (pchs_amt가 0이면 0%)
  const erngPct = summary.pchs_amt > 0
    ? (summary.evlu_pfls_amt / summary.pchs_amt) * 100
    : 0

  return (
    <Card>
      <CardHeader
        title="계좌 현황"
        subtitle={summary.created_at ? formatTimeAgo(summary.created_at) + ' 기준' : undefined}
        action={<Wallet className="w-4 h-4 text-[#555570]" />}
      />

      {/* 총 평가금액 강조 */}
      <div className="mb-4">
        <p className="text-xs text-[#555570] mb-0.5">총 평가금액</p>
        <p className="text-2xl font-bold text-[#f0f0f8]">
          {formatPrice(summary.tot_evlu_amt)}
        </p>
        <p className={`text-sm font-semibold mt-0.5 ${pnlColor}`}>
          {isPnlPositive ? '+' : ''}{formatPrice(summary.evlu_pfls_amt)}&nbsp;
          ({formatPct(erngPct)})
        </p>
      </div>

      {/* 세부 항목 */}
      <div>
        <SummaryRow label="예수금 (현금)" value={formatPrice(summary.cash_amt)} />
        <SummaryRow label="주식 평가금액" value={formatPrice(summary.stock_evlu_amt)} />
        <SummaryRow label="매수 원가" value={formatPrice(summary.pchs_amt)} />
        <SummaryRow
          label="평가 손익"
          value={`${isPnlPositive ? '+' : ''}${formatPrice(summary.evlu_pfls_amt)}`}
          valueClass={pnlColor}
        />
      </div>
    </Card>
  )
}
