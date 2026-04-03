'use client'

import type { KISAccountSummary } from '@/lib/kis-types'
import { formatKRW, formatPct } from '@/lib/format'

interface KISBalanceSummaryProps {
  summary: KISAccountSummary
}

interface CellProps {
  label: string
  value: string
  highlight?: 'profit' | 'loss' | 'accent' | null
  sub?: string
}

function SummaryCell({ label, value, highlight, sub }: CellProps) {
  const colorClass =
    highlight === 'profit' ? 'text-red-400' :
    highlight === 'loss' ? 'text-blue-400' :
    highlight === 'accent' ? 'text-amber-400' :
    'text-[#f0f0f8]'

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-[#555570]">{label}</span>
      <span className={`text-sm font-semibold ${colorClass}`}>{value}</span>
      {sub && <span className="text-xs text-[#555570]">{sub}</span>}
    </div>
  )
}

export function KISBalanceSummary({ summary }: KISBalanceSummaryProps) {
  const pnlHighlight = summary.evluPflsAmt >= 0 ? 'profit' : 'loss'

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
      <SummaryCell
        label="총 평가금액"
        value={formatKRW(summary.totEvluAmt)}
        highlight="accent"
      />
      <SummaryCell
        label="예수금 (현금)"
        value={formatKRW(summary.cashAmt)}
      />
      <SummaryCell
        label="유가 평가액"
        value={formatKRW(summary.stockEvluAmt)}
      />
      <SummaryCell
        label="매입 금액"
        value={formatKRW(summary.pchsAmt)}
      />
      <SummaryCell
        label="평가 손익"
        value={formatKRW(summary.evluPflsAmt)}
        highlight={pnlHighlight}
        sub={summary.erngRt != null ? formatPct(summary.erngRt) : '-'}
      />
      <SummaryCell
        label="순자산"
        value={formatKRW(summary.nassAmt)}
      />
      <SummaryCell
        label="금일 매수/매도"
        value={`${formatKRW(summary.thdtBuyAmt)} / ${formatKRW(summary.thdtSllAmt)}`}
      />
      <SummaryCell
        label="자산 증감"
        value={formatKRW(summary.asstIcdcAmt)}
        highlight={summary.asstIcdcAmt >= 0 ? 'profit' : 'loss'}
        sub={formatPct(summary.asstIcdcErngRt)}
      />
    </div>
  )
}
