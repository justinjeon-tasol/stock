'use client'

import type { DataSource } from '@/lib/kis-types'
import { formatTimeAgo } from '@/lib/format'

interface DataSourceBadgeProps {
  source: DataSource
  fetchedAt?: string | null
}

const CONFIG: Record<DataSource, { dot: string; label: string }> = {
  KIS: { dot: 'bg-emerald-400', label: 'KIS 실시간' },
  SUPABASE: { dot: 'bg-[#555570]', label: 'Supabase 이력' },
  KIS_FALLBACK: { dot: 'bg-yellow-400', label: 'KIS 오류 → Supabase' },
}

export function DataSourceBadge({ source, fetchedAt }: DataSourceBadgeProps) {
  const { dot, label } = CONFIG[source]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#8888a8] bg-[#1a1a24] px-2.5 py-1 rounded-full border border-[#2a2a38]">
      <span className={`w-1.5 h-1.5 rounded-full ${dot} animate-pulse`} />
      <span>{label}</span>
      {fetchedAt && (
        <span className="text-[#555570]">· {formatTimeAgo(fetchedAt)}</span>
      )}
    </span>
  )
}
