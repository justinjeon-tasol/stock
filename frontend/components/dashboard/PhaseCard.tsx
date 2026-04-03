'use client'

import { Activity } from 'lucide-react'
import { useMarketPhase } from '@/hooks/useMarketPhase'
import { Card, CardHeader } from '@/components/ui/Card'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { getPhaseToken } from '@/lib/phase-tokens'

export function PhaseCard() {
  const { phase, loading, error } = useMarketPhase()

  if (loading) return <SkeletonCard />
  if (error || !phase) {
    return (
      <Card>
        <p className="text-xs text-[#f87171]">국면 데이터 없음</p>
      </Card>
    )
  }

  const token = getPhaseToken(phase.phase)
  const confidencePct = Math.round(phase.confidence * 100)

  // 경과일 계산
  const startDate = phase.start_date ? new Date(phase.start_date) : null
  const elapsedDays = startDate
    ? Math.floor((Date.now() - startDate.getTime()) / 86400000)
    : 0

  // 원형 프로그레스바 SVG 파라미터
  const r = 36
  const circumference = 2 * Math.PI * r
  const offset = circumference - (confidencePct / 100) * circumference

  return (
    <Card
      style={{
        borderColor: token.border,
        boxShadow: `0 0 24px ${token.glow}`,
      }}
    >
      <CardHeader
        title="현재 국면"
        action={<Activity className="w-4 h-4 text-[#555570]" />}
      />

      <div className="flex items-center gap-5">
        {/* 원형 신뢰도 게이지 */}
        <div className="relative flex-shrink-0">
          <svg width="88" height="88" viewBox="0 0 88 88">
            {/* 배경 원 */}
            <circle
              cx="44"
              cy="44"
              r={r}
              fill="none"
              stroke="#2a2a38"
              strokeWidth="6"
            />
            {/* 진행 원 */}
            <circle
              cx="44"
              cy="44"
              r={r}
              fill="none"
              stroke={token.border}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              transform="rotate(-90 44 44)"
              style={{ transition: 'stroke-dashoffset 0.5s ease' }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold" style={{ color: token.text }}>
              {confidencePct}%
            </span>
            <span className="text-[10px] text-[#555570]">신뢰도</span>
          </div>
        </div>

        {/* 국면 정보 */}
        <div className="flex-1 min-w-0">
          {/* 국면 배지 */}
          <div
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-sm font-bold mb-2"
            style={{ backgroundColor: token.bg, color: token.text }}
          >
            <span>{token.emoji}</span>
            <span>{token.label}</span>
          </div>

          {/* 경과일 */}
          <p className="text-xs text-[#8888a8]">
            경과{' '}
            <span className="font-semibold text-[#f0f0f8]">{elapsedDays}일</span>
          </p>

          {/* 시작일 */}
          {phase.start_date && (
            <p className="text-xs text-[#555570] mt-0.5">
              {new Date(phase.start_date).toLocaleDateString('ko-KR', {
                month: 'short',
                day: 'numeric',
              })}{' '}
              시작
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}
