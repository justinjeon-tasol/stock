import React from 'react'
import { Inbox } from 'lucide-react'

interface EmptyStateProps {
  title?: string
  description?: string
  icon?: React.ReactNode
}

export function EmptyState({
  title = '데이터 없음',
  description = '표시할 항목이 없습니다.',
  icon,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-[#3a3a4e] mb-3">
        {icon ?? <Inbox className="w-10 h-10" />}
      </div>
      <p className="text-sm font-medium text-[#8888a8]">{title}</p>
      <p className="text-xs text-[#555570] mt-1">{description}</p>
    </div>
  )
}
