'use client'

import type { KISHolding, KISAccountSummary } from '@/lib/kis-types'
import { formatKRW, formatPct } from '@/lib/format'

interface KISHoldingsTableProps {
  holdings: KISHolding[]
  summary?: KISAccountSummary
}

export function KISHoldingsTable({ holdings, summary }: KISHoldingsTableProps) {
  if (holdings.length === 0) {
    return (
      <div className="text-center py-8 text-[#555570] text-sm">
        보유 종목이 없습니다
      </div>
    )
  }

  const totalEvluAmt = summary?.stockEvluAmt ?? holdings.reduce((acc, h) => acc + h.evluAmt, 0)
  const totalPflsAmt = summary?.evluPflsAmt ?? holdings.reduce((acc, h) => acc + h.evluPflsAmt, 0)
  const totalErngRt = summary?.erngRt

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[#555570] text-xs border-b border-[#2a2a38]">
            <th className="text-left py-2 px-2">종목</th>
            <th className="text-right py-2 px-2">수량</th>
            <th className="text-right py-2 px-2">매입평균</th>
            <th className="text-right py-2 px-2">현재가</th>
            <th className="text-right py-2 px-2">전일대비</th>
            <th className="text-right py-2 px-2">평가금액</th>
            <th className="text-right py-2 px-2">평가손익</th>
            <th className="text-right py-2 px-2">수익률</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => {
            const pnlColor = h.evluPflsAmt >= 0 ? 'text-red-400' : 'text-blue-400'
            const dayColor = h.dayChange > 0 ? 'text-red-400' : h.dayChange < 0 ? 'text-blue-400' : 'text-[#8888a8]'

            return (
              <tr key={h.code} className="border-b border-[#1a1a24] hover:bg-[#1a1a24]/50">
                <td className="py-2.5 px-2">
                  <div className="font-medium text-[#f0f0f8]">{h.name}</div>
                  <div className="text-xs text-[#555570]">{h.code}</div>
                </td>
                <td className="text-right py-2.5 px-2 text-[#f0f0f8]">{h.quantity.toLocaleString('ko-KR')}</td>
                <td className="text-right py-2.5 px-2 text-[#8888a8]">{formatKRW(h.avgPrice)}</td>
                <td className="text-right py-2.5 px-2 text-[#f0f0f8] font-medium">{formatKRW(h.currentPrice)}</td>
                <td className={`text-right py-2.5 px-2 ${dayColor}`}>
                  <div>{h.dayChange > 0 ? '+' : ''}{formatKRW(h.dayChange)}</div>
                  <div className="text-xs">{formatPct(h.dayChangeRt)}</div>
                </td>
                <td className="text-right py-2.5 px-2 text-[#f0f0f8]">{formatKRW(h.evluAmt)}</td>
                <td className={`text-right py-2.5 px-2 ${pnlColor}`}>
                  {h.evluPflsAmt >= 0 ? '+' : ''}{formatKRW(h.evluPflsAmt)}
                </td>
                <td className={`text-right py-2.5 px-2 font-semibold ${pnlColor}`}>
                  {formatPct(h.evluPflsRt)}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-[#3a3a4e] text-[#f0f0f8] font-semibold">
            <td className="py-2.5 px-2" colSpan={5}>합계</td>
            <td className="text-right py-2.5 px-2">{formatKRW(totalEvluAmt)}</td>
            <td className={`text-right py-2.5 px-2 ${totalPflsAmt >= 0 ? 'text-red-400' : 'text-blue-400'}`}>
              {totalPflsAmt >= 0 ? '+' : ''}{formatKRW(totalPflsAmt)}
            </td>
            <td className={`text-right py-2.5 px-2 ${totalPflsAmt >= 0 ? 'text-red-400' : 'text-blue-400'}`}>
              {totalErngRt != null ? formatPct(totalErngRt) : '-'}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
