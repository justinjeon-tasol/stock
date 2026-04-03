import { AgentGrid } from '@/components/agents/AgentGrid'

export default function AgentsPage() {
  return (
    <div className="space-y-6 animate-slide-in">
      <div>
        <h1 className="text-xl font-bold text-[#f0f0f8]">에이전트</h1>
        <p className="text-xs text-[#555570] mt-0.5">7개 에이전트 실시간 상태 모니터링</p>
      </div>

      <AgentGrid />
    </div>
  )
}
