'use client'

import { Clock, FileCode, AlertCircle } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { StatusIcon } from './StatusIcon'
import { formatTimeAgo } from '@/lib/format'
import type { AgentStatusInfo } from '@/lib/types'
import { cn } from '@/lib/cn'

const LAYER_COLORS = {
  지휘: { bg: '#2e1065', text: '#a78bfa', border: '#7c3aed' },
  데이터: { bg: '#0c4a6e', text: '#38bdf8', border: '#0284c7' },
  전략: { bg: '#064e3b', text: '#34d399', border: '#059669' },
  운영: { bg: '#451a03', text: '#fb923c', border: '#ea580c' },
}

const STATUS_BORDER: Record<string, string> = {
  CRITICAL: '#dc2626',
  ERROR:    '#ea580c',
  WARNING:  '#d97706',
  OFFLINE:  '#555570',
  NORMAL:   '',
}

interface AgentCardProps {
  agent: AgentStatusInfo
}

export function AgentCard({ agent }: AgentCardProps) {
  const { meta, status, lastLog, lastSeen } = agent
  const layerColor = LAYER_COLORS[meta.layer]
  const statusBorder = STATUS_BORDER[status]

  return (
    <Card
      className={cn(
        'transition-all duration-200 hover:scale-[1.01]',
        status !== 'NORMAL' && status !== 'OFFLINE' && 'animate-pulse-glow'
      )}
      style={
        {
          borderColor: statusBorder || '#2a2a38',
          boxShadow: statusBorder ? `0 0 12px ${statusBorder}30` : undefined,
        } as React.CSSProperties
      }
    >
      {/* 헤더 */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <StatusIcon status={status} size="md" />
          <div>
            <h3 className="text-sm font-semibold text-[#f0f0f8]">{meta.name}</h3>
            <span
              className="text-xs px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: layerColor.bg,
                color: layerColor.text,
              }}
            >
              {meta.layer}
            </span>
          </div>
        </div>
        <span className="text-xs font-mono text-[#555570] bg-[#22222e] px-1.5 py-0.5 rounded">
          {meta.code}
        </span>
      </div>

      {/* 설명 */}
      <p className="text-xs text-[#8888a8] mb-3 leading-relaxed">
        {meta.description}
      </p>

      {/* 파일명 */}
      <div className="flex items-center gap-1.5 text-xs text-[#555570] mb-3">
        <FileCode className="w-3.5 h-3.5" />
        <span className="font-mono">{meta.file}</span>
      </div>

      {/* 마지막 로그 */}
      {lastLog && (
        <div
          className="rounded-lg p-2 text-xs"
          style={{
            backgroundColor: '#0a0a0f',
            border: '1px solid #2a2a38',
          }}
        >
          <div className="flex items-center justify-between mb-1">
            <span
              className="font-medium"
              style={{
                color:
                  lastLog.level === 'CRITICAL' ? '#f87171'
                  : lastLog.level === 'ERROR'    ? '#fb923c'
                  : lastLog.level === 'WARNING'  ? '#fbbf24'
                  : '#4ade80',
              }}
            >
              {lastLog.level}
            </span>
            <span className="text-[#555570]">{formatTimeAgo(lastLog.timestamp)}</span>
          </div>
          <p className="text-[#8888a8] truncate" title={lastLog.message}>
            {lastLog.message}
          </p>
          {lastLog.error_code && (
            <span className="text-[#555570] font-mono mt-1 block">
              [{lastLog.error_code}]
            </span>
          )}
        </div>
      )}

      {!lastLog && (
        <div className="rounded-lg p-2 bg-[#0a0a0f] border border-[#2a2a38]">
          <p className="text-xs text-[#555570] flex items-center gap-1.5">
            <AlertCircle className="w-3 h-3" />
            로그 없음
          </p>
        </div>
      )}

      {/* 마지막 확인 시간 */}
      {lastSeen && (
        <div className="flex items-center gap-1 text-xs text-[#555570] mt-2">
          <Clock className="w-3 h-3" />
          <span>마지막 확인: {formatTimeAgo(lastSeen)}</span>
        </div>
      )}
    </Card>
  )
}
