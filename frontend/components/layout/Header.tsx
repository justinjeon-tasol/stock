'use client'

import { RefreshCw, Clock } from 'lucide-react'
import { useMarketPhase } from '@/hooks/useMarketPhase'
import { getPhaseToken } from '@/lib/phase-tokens'
import { Badge } from '@/components/ui/Badge'
import { formatTimeAgo } from '@/lib/format'

export function Header() {
  const { phase, loading, refetch } = useMarketPhase()
  const token = getPhaseToken(phase?.phase ?? null)

  return (
    <header
      className="fixed top-0 right-0 z-30 flex items-center justify-between h-16 px-6 border-b"
      style={{
        left: 'var(--sidebar-width, 240px)',
        backgroundColor: '#111118',
        borderColor: '#2a2a38',
      }}
    >
      {/* 현재 국면 표시 */}
      <div className="flex items-center gap-3">
        {loading ? (
          <div className="h-6 w-28 rounded-full bg-[#22222e] animate-pulse" />
        ) : phase ? (
          <Badge
            style={{
              backgroundColor: token.bg,
              color: token.text,
              borderColor: token.border,
              boxShadow: `0 0 12px ${token.glow}`,
            }}
            size="md"
          >
            {token.emoji} {token.label}
          </Badge>
        ) : (
          <span className="text-xs text-[#555570]">국면 정보 없음</span>
        )}

        {phase && (
          <div className="flex items-center gap-1 text-xs text-[#555570]">
            <Clock className="w-3 h-3" />
            <span>{formatTimeAgo(phase.created_at ?? phase.start_date)}</span>
          </div>
        )}
      </div>

      {/* 우측 액션 */}
      <div className="flex items-center gap-3">
        {phase && (
          <div className="text-xs text-[#555570]">
            신뢰도{' '}
            <span className="text-[#8888a8] font-medium">
              {(phase.confidence * 100).toFixed(0)}%
            </span>
          </div>
        )}

        <button
          onClick={refetch}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#1a1a24] transition-colors"
          title="데이터 새로고침"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>새로고침</span>
        </button>

        {/* 시스템 상태 표시 */}
        <div className="flex items-center gap-1.5 text-xs text-[#555570]">
          <span className="w-2 h-2 rounded-full bg-[#4ade80] animate-pulse inline-block" />
          <span>실시간</span>
        </div>
      </div>
    </header>
  )
}
