'use client'

import type { WinLossStatsData } from '@/lib/kis-types'
import { Card } from '@/components/ui/Card'

interface WinLossStatsProps {
  stats: WinLossStatsData
}

interface StatCardProps {
  label: string
  value: string
  sub?: string
  highlight?: 'good' | 'bad' | 'neutral'
}

function StatCard({ label, value, sub, highlight = 'neutral' }: StatCardProps) {
  const colorClass =
    highlight === 'good' ? 'text-emerald-400' :
    highlight === 'bad' ? 'text-red-400' :
    'text-[#f0f0f8]'

  return (
    <div className="bg-[#1a1a24] rounded-lg p-3 border border-[#2a2a38]">
      <div className="text-xs text-[#555570] mb-1">{label}</div>
      <div className={`text-lg font-bold ${colorClass}`}>{value}</div>
      {sub && <div className="text-xs text-[#555570] mt-0.5">{sub}</div>}
    </div>
  )
}

export function WinLossStats({ stats }: WinLossStatsProps) {
  const winRateHighlight = stats.winRate >= 55 ? 'good' : stats.winRate >= 45 ? 'neutral' : 'bad'
  const pfHighlight = stats.profitFactor >= 1.5 ? 'good' : stats.profitFactor >= 1 ? 'neutral' : 'bad'

  return (
    <Card>
      <div className="text-sm font-semibold text-[#8888a8] uppercase tracking-wider mb-4">
        매매 통계
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="총 매매 수"
          value={`${stats.totalTrades}건`}
        />
        <StatCard
          label="승률"
          value={`${stats.winRate.toFixed(1)}%`}
          highlight={winRateHighlight}
        />
        <StatCard
          label="평균 수익"
          value={`+${stats.avgWinPct.toFixed(2)}%`}
          highlight="good"
        />
        <StatCard
          label="평균 손실"
          value={`${stats.avgLossPct.toFixed(2)}%`}
          highlight="bad"
        />
        <StatCard
          label="프로핏 팩터"
          value={stats.profitFactor === Infinity ? '∞' : stats.profitFactor.toFixed(2)}
          highlight={pfHighlight}
          sub="총수익/총손실"
        />
        <StatCard
          label="최대 연승"
          value={`${stats.maxConsecutiveWins}연승`}
          highlight="good"
        />
        <StatCard
          label="최대 연패"
          value={`${stats.maxConsecutiveLosses}연패`}
          highlight={stats.maxConsecutiveLosses >= 5 ? 'bad' : 'neutral'}
        />
        <StatCard
          label="누적 수익률"
          value={`${stats.totalRealizedPnl >= 0 ? '+' : ''}${stats.totalRealizedPnl.toFixed(2)}%`}
          highlight={stats.totalRealizedPnl >= 0 ? 'good' : 'bad'}
        />
      </div>
    </Card>
  )
}
