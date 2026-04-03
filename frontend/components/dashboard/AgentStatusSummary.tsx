'use client'

import { useAgentLogs } from '@/hooks/useAgentLogs'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { StatusIcon } from '@/components/agents/StatusIcon'
import type { AgentStatus } from '@/lib/types'

const STATUS_LABEL: Record<AgentStatus, string> = {
  NORMAL: '정상',
  WARNING: '경고',
  ERROR: '오류',
  CRITICAL: '심각',
  OFFLINE: '오프라인',
}

const STATUS_COLOR: Record<AgentStatus, string> = {
  NORMAL: '#4ade80',
  WARNING: '#fbbf24',
  ERROR: '#f97316',
  CRITICAL: '#f87171',
  OFFLINE: '#555570',
}

export function AgentStatusSummary() {
  const { agents, loading, error } = useAgentLogs()

  if (loading) return <SkeletonCard />
  if (error) {
    return (
      <Card>
        <p className="text-xs text-[#f87171]">에이전트 상태 로드 오류</p>
      </Card>
    )
  }

  const counts: Record<AgentStatus, number> = {
    NORMAL: 0,
    WARNING: 0,
    ERROR: 0,
    CRITICAL: 0,
    OFFLINE: 0,
  }
  for (const a of agents) counts[a.status]++

  const hasCritical = counts.CRITICAL > 0 || counts.ERROR > 0
  const displayStatuses: AgentStatus[] = ['NORMAL', 'WARNING', 'ERROR', 'CRITICAL', 'OFFLINE']

  return (
    <Card
      style={
        hasCritical
          ? { borderColor: '#dc2626', animation: 'pulse 1s infinite' }
          : undefined
      }
    >
      <CardHeader
        title="에이전트 상태"
        subtitle={`총 ${agents.length}개`}
      />

      {/* 상태 요약 숫자 */}
      <div className="space-y-2">
        {displayStatuses.map((status) => (
          <div key={status} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <StatusIcon status={status} size="sm" />
              <span className="text-xs text-[#8888a8]">{STATUS_LABEL[status]}</span>
            </div>
            <span
              className="text-sm font-bold tabular-nums"
              style={{ color: STATUS_COLOR[status] }}
            >
              {counts[status]}
            </span>
          </div>
        ))}
      </div>

      {/* 최근 오류 메시지 */}
      {hasCritical && (
        <div className="mt-3 pt-3 border-t border-[#2a2a38]">
          {agents
            .filter((a) => a.status === 'CRITICAL' || a.status === 'ERROR')
            .slice(0, 2)
            .map((a) => (
              <p key={a.code} className="text-xs text-[#f87171] truncate">
                [{a.code}] {a.lastLog?.message ?? '오류 발생'}
              </p>
            ))}
        </div>
      )}
    </Card>
  )
}
