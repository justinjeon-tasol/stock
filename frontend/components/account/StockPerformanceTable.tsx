'use client'

import { useState } from 'react'
import type { StockReturn } from '@/lib/kis-types'
import { formatPct } from '@/lib/format'
import { Card, CardHeader } from '@/components/ui/Card'

interface StockPerformanceTableProps {
  data: StockReturn[]
}

type SortKey = 'totalPnl' | 'winRate' | 'tradeCount'

export function StockPerformanceTable({ data }: StockPerformanceTableProps) {
  const [sortBy, setSortBy] = useState<SortKey>('totalPnl')

  const sorted = [...data].sort((a, b) => {
    if (sortBy === 'totalPnl') return b.totalPnl - a.totalPnl
    if (sortBy === 'winRate') return b.winRate - a.winRate
    return b.tradeCount - a.tradeCount
  })

  const headers: { key: SortKey; label: string }[] = [
    { key: 'totalPnl', label: '총 손익' },
    { key: 'winRate', label: '승률' },
    { key: 'tradeCount', label: '거래수' },
  ]

  return (
    <Card>
      <CardHeader
        title="종목별 실현 손익"
        subtitle={`${data.length}개 종목`}
        action={
          <div className="flex gap-1">
            {headers.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setSortBy(key)}
                className={`px-2 py-0.5 text-xs rounded ${
                  sortBy === key
                    ? 'bg-[#7c6af7] text-white'
                    : 'bg-[#1a1a24] text-[#8888a8] hover:bg-[#22222e]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        }
      />
      {sorted.length === 0 ? (
        <div className="text-center py-6 text-[#555570] text-sm">매매 이력이 없습니다</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#555570] text-xs border-b border-[#2a2a38]">
                <th className="text-left py-2 px-2">종목</th>
                <th className="text-right py-2 px-2">거래수</th>
                <th className="text-right py-2 px-2">승/패</th>
                <th className="text-right py-2 px-2">승률</th>
                <th className="text-right py-2 px-2">평균 수익률</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
                const pnlColor = s.totalPnlPct >= 0 ? 'text-red-400' : 'text-blue-400'
                return (
                  <tr key={s.code} className="border-b border-[#1a1a24] hover:bg-[#1a1a24]/50">
                    <td className="py-2 px-2">
                      <div className="text-[#f0f0f8] font-medium">{s.name}</div>
                      <div className="text-xs text-[#555570]">{s.code}</div>
                    </td>
                    <td className="text-right py-2 px-2 text-[#8888a8]">{s.tradeCount}</td>
                    <td className="text-right py-2 px-2 text-[#8888a8]">
                      {s.winCount}/{s.tradeCount - s.winCount}
                    </td>
                    <td className="text-right py-2 px-2">
                      <span className={s.winRate >= 50 ? 'text-emerald-400' : 'text-[#8888a8]'}>
                        {s.winRate.toFixed(1)}%
                      </span>
                    </td>
                    <td className={`text-right py-2 px-2 font-semibold ${pnlColor}`}>
                      {formatPct(s.totalPnlPct)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
