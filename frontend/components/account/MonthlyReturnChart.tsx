'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { Card, CardHeader } from '@/components/ui/Card'
import type { PeriodReturn } from '@/lib/kis-types'

interface MonthlyReturnChartProps {
  data: PeriodReturn[]
}

export function MonthlyReturnChart({ data }: MonthlyReturnChartProps) {
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader title="월별 수익률" subtitle="데이터 없음" />
        <div className="h-48 flex items-center justify-center text-[#555570] text-sm">
          매매 이력이 없습니다
        </div>
      </Card>
    )
  }

  const chartData = data.map((d) => ({
    month: d.period.slice(5), // "01", "02" ...
    returnPct: Number(d.returnPct.toFixed(2)),
    count: d.tradeCount,
    wins: d.winCount,
  }))

  return (
    <Card>
      <CardHeader title="월별 수익률" subtitle="평균 수익률 (%)" />
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2a38" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fill: '#555570', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#555570', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1a1a24',
                border: '1px solid #3a3a4e',
                borderRadius: '8px',
                fontSize: 12,
                color: '#f0f0f8',
              }}
              formatter={(value: number) => [`${value >= 0 ? '+' : ''}${value}%`, '수익률']}
              labelStyle={{ color: '#8888a8' }}
            />
            <Bar dataKey="returnPct" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, idx) => (
                <Cell
                  key={idx}
                  fill={entry.returnPct >= 0 ? '#4ade80' : '#f87171'}
                  fillOpacity={0.8}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
