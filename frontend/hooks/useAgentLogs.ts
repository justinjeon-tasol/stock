'use client'

import { useState, useEffect, useCallback } from 'react'
import { supabase } from '@/lib/supabase'
import { AGENT_META, AGENT_CODES } from '@/lib/agent-meta'
import type { AgentLog, AgentStatus, AgentStatusInfo } from '@/lib/types'

// 에이전트 상태 판단 기준 (초)
const OFFLINE_THRESHOLD = 90
const WARNING_THRESHOLD = 30

function deriveStatus(log: AgentLog | null): AgentStatus {
  if (!log) return 'OFFLINE'

  const level = log.level
  if (level === 'CRITICAL') return 'CRITICAL'
  if (level === 'ERROR') return 'ERROR'
  if (level === 'WARNING') return 'WARNING'

  // INFO 레벨: 마지막 로그 시간 확인
  const diffSec = (Date.now() - new Date(log.timestamp).getTime()) / 1000
  if (diffSec > OFFLINE_THRESHOLD) return 'OFFLINE'
  if (diffSec > WARNING_THRESHOLD) return 'WARNING'
  return 'NORMAL'
}

interface UseAgentLogsResult {
  agents: AgentStatusInfo[]
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useAgentLogs(): UseAgentLogsResult {
  const [agents, setAgents] = useState<AgentStatusInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)

    const { data, error: err } = await supabase
      .from('agent_logs')
      .select('*')
      .order('timestamp', { ascending: false })
      .limit(200)

    if (err) {
      setError(err.message)
      setLoading(false)
      return
    }

    const logs = (data ?? []) as AgentLog[]

    // 에이전트별 가장 최근 로그 추출
    const latestByAgent: Record<string, AgentLog> = {}
    for (const log of logs) {
      if (!latestByAgent[log.agent]) {
        latestByAgent[log.agent] = log
      }
    }

    const result: AgentStatusInfo[] = AGENT_CODES.map((code) => {
      const lastLog = latestByAgent[code] ?? null
      return {
        code,
        meta: AGENT_META[code],
        status: deriveStatus(lastLog),
        lastLog,
        lastSeen: lastLog?.timestamp ?? null,
      }
    })

    setAgents(result)
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchLogs()
    // 30초마다 자동 갱신
    const interval = setInterval(fetchLogs, 30_000)
    return () => clearInterval(interval)
  }, [fetchLogs])

  return { agents, loading, error, refetch: fetchLogs }
}
