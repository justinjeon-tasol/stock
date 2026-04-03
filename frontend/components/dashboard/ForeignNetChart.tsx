'use client'

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { Card, CardHeader } from '@/components/ui/Card'
import type { ForeignNetDataPoint } from '@/lib/types'

// 임시 placeholder 데이터 (실제 데이터로 교체 시 props로 주입)
const PLACEHOLDER_DATA: ForeignNetDataPoint[] = [
  { date: '03-25', value: -3200 },
  { date: '03-26', value: -1800 },
  { date: '03-27', value: 2400 },
  { date: '03-28', value: 1200 },
  { date: '03-31', value: -800 },
  { date: '04-01', value: 3100 },
  { date: '04-02', value: 2700 },
  { date: '04-03', value: -500 },
  { date: '04-04', value: 4200 },
  { date: '04-07', value: 1900 },
]

interface ForeignNetChartProps {
  data?: ForeignNetDataPoint[]
  title?: string
}

function formatBillionKRW(value: number): string {
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(1)}조`
  }
  return `${value}억`
}

export function ForeignNetChart({
  data = PLACEHOLDER_DATA,
  title = '외국인 순매수',
}: ForeignNetChartProps) {
  return (
    <Card>
      <CardHeader
        title={title}
        subtitle="최근 10거래일 (억원)"
        action={
          <span className="text-xs text-[#555570] bg-[#22222e] px-2 py-0.5 rounded">
            Placeholder
          </span>
        }
      />

      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="foreignNetPos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#4ade80" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#4ade80" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="foreignNetNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2a38" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: '#555570', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#555570', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={formatBillionKRW}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1a1a24',
                border: '1px solid #3a3a4e',
                borderRadius: '8px',
                fontSize: 12,
                color: '#f0f0f8',
              }}
              formatter={(value: number) => [
                `${value >= 0 ? '+' : ''}${formatBillionKRW(value)}`,
                '외국인 순매수',
              ]}
              labelStyle={{ color: '#8888a8' }}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="#7c6af7"
              strokeWidth={2}
              fill="url(#foreignNetPos)"
              dot={false}
              activeDot={{ r: 4, fill: '#7c6af7' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
