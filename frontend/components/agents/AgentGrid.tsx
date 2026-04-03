'use client'

import { RefreshCw } from 'lucide-react'
import { useAgentLogs } from '@/hooks/useAgentLogs'
import { AgentCard } from './AgentCard'
import { SkeletonCard } from '@/components/ui/Skeleton'
import type { AgentStatus } from '@/lib/types'

const STATUS_LABELS: Record<AgentStatus, string> = {
  NORMAL:   '정상',
  WARNING:  '경고',
  ERROR:    '오류',
  CRITICAL: '심각',
  OFFLINE:  '오프라인',
}

export function AgentGrid() {
  const { agents, loading, error, refetch } = useAgentLogs()

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {Array.from({ length: 7 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    )
  }

  if (error) {
    return <p className="text-sm text-[#f87171]">로드 오류: {error}</p>
  }

  const statusCounts = agents.reduce(
    (acc, a) => {
      acc[a.status] = (acc[a.status] ?? 0) + 1
      return acc
    },
    {} as Record<AgentStatus, number>
  )

  return (
    <div className="space-y-4">
      {/* 요약 상태 바 */}
      <div className="flex flex-wrap items-center gap-4 p-3 bg-[#111118] border border-[#2a2a38] rounded-xl">
        <span className="text-xs text-[#555570]">총 {agents.length}개 에이전트</span>
        <div className="flex gap-3">
          {(Object.entries(statusCounts) as [AgentStatus, number][]).map(
            ([status, count]) => (
              <div key={status} className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full inline-block"
                  style={{
                    backgroundColor:
                      status === 'NORMAL'   ? '#4ade80'
                      : status === 'WARNING'  ? '#fbbf24'
                      : status === 'ERROR'    ? '#fb923c'
                      : status === 'CRITICAL' ? '#f87171'
                      : '#555570',
                  }}
                />
                <span className="text-xs text-[#8888a8]">
                  {STATUS_LABELS[status]} {count}
                </span>
              </div>
            )
          )}
        </div>

        <button
          onClick={refetch}
          className="ml-auto flex items-center gap-1 text-xs text-[#555570] hover:text-[#8888a8] transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          새로고침
        </button>
      </div>

      {/* 에이전트 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {agents.map((agent) => (
          <AgentCard key={agent.code} agent={agent} />
        ))}
      </div>
    </div>
  )
}
