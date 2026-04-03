import { PhaseCard } from '@/components/dashboard/PhaseCard'
import { PositionSummaryCard } from '@/components/dashboard/PositionSummaryCard'
import { AgentStatusSummary } from '@/components/dashboard/AgentStatusSummary'
import { AccountSummaryCard } from '@/components/dashboard/AccountSummaryCard'
import { ForeignNetChart } from '@/components/dashboard/ForeignNetChart'
import { RecentSignalList } from '@/components/dashboard/RecentSignalList'

export default function DashboardPage() {
  return (
    <div className="space-y-6 animate-slide-in">
      <div>
        <h1 className="text-xl font-bold text-[#f0f0f8]">대시보드</h1>
        <p className="text-xs text-[#555570] mt-0.5">실시간 자동매매 현황</p>
      </div>

      {/* 상단 3열 요약 카드 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <PhaseCard />
        <AccountSummaryCard />
        <AgentStatusSummary />
      </div>

      {/* 중단 2열 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PositionSummaryCard />
        <RecentSignalList />
      </div>

      {/* 하단 */}
      <ForeignNetChart />
    </div>
  )
}
