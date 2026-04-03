import { cn } from '@/lib/cn'
import type { AgentStatus } from '@/lib/types'

interface StatusIconProps {
  status: AgentStatus
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
}

const STATUS_CONFIG: Record<AgentStatus, { color: string; label: string; pulse: boolean }> = {
  NORMAL:   { color: '#4ade80', label: '정상', pulse: true },
  WARNING:  { color: '#fbbf24', label: '경고', pulse: true },
  ERROR:    { color: '#fb923c', label: '오류', pulse: false },
  CRITICAL: { color: '#f87171', label: '심각', pulse: true },
  OFFLINE:  { color: '#555570', label: '오프라인', pulse: false },
}

export function StatusIcon({ status, size = 'md', showLabel = false }: StatusIconProps) {
  const config = STATUS_CONFIG[status]
  const sizePx = size === 'sm' ? 8 : size === 'md' ? 10 : 14

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative inline-flex">
        {config.pulse && (
          <span
            className="absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping"
            style={{ backgroundColor: config.color }}
          />
        )}
        <span
          className="relative inline-flex rounded-full"
          style={{
            width: sizePx,
            height: sizePx,
            backgroundColor: config.color,
          }}
        />
      </span>
      {showLabel && (
        <span
          className="text-xs font-medium"
          style={{ color: config.color }}
        >
          {config.label}
        </span>
      )}
    </span>
  )
}

export function StatusDot({ status }: { status: AgentStatus }) {
  const config = STATUS_CONFIG[status]
  return (
    <span
      className="inline-block w-2 h-2 rounded-full"
      style={{ backgroundColor: config.color }}
      title={config.label}
    />
  )
}
