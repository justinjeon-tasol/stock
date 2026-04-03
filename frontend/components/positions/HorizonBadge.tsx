import { Badge } from '@/components/ui/Badge'
import type { HoldingPeriod } from '@/lib/types'

interface HorizonBadgeProps {
  period: HoldingPeriod
}

const HORIZON_TOKENS: Record<HoldingPeriod, { bg: string; text: string; label: string }> = {
  초단기: { bg: '#450a0a', text: '#fca5a5', label: '초단기' },
  단기:   { bg: '#431407', text: '#fdba74', label: '단기' },
  중기:   { bg: '#172554', text: '#93c5fd', label: '중기' },
  장기:   { bg: '#052e16', text: '#86efac', label: '장기' },
}

export function HorizonBadge({ period }: HorizonBadgeProps) {
  const token = HORIZON_TOKENS[period] ?? HORIZON_TOKENS['단기']

  return (
    <Badge
      style={{
        backgroundColor: token.bg,
        color: token.text,
        borderColor: token.text + '40',
      }}
    >
      {token.label}
    </Badge>
  )
}
