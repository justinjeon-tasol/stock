'use client'

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { Card, CardHeader } from '@/components/ui/Card'

interface DataPoint {
  date: string
  value: number
}

interface EquityCurveChartProps {
  data: DataPoint[]
}

function formatEok(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)}억`
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}만`
  return `${v}`
}

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader title="자산 추이" subtitle="데이터 없음" />
        <div className="h-48 flex items-center justify-center text-[#555570] text-sm">
          계좌 이력이 없습니다
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader title="자산 추이" subtitle="총 평가금액 변화" />
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
            <defs>
              <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#7c6af7" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#7c6af7" stopOpacity={0} />
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
              tickFormatter={formatEok}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1a1a24',
                border: '1px solid #3a3a4e',
                borderRadius: '8px',
                fontSize: 12,
                color: '#f0f0f8',
              }}
              formatter={(value: number) => [formatEok(value), '총 평가']}
              labelStyle={{ color: '#8888a8' }}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="#7c6af7"
              strokeWidth={2}
              fill="url(#equityGrad)"
              dot={false}
              activeDot={{ r: 4, fill: '#7c6af7' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
