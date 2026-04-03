import React from 'react'
import { cn } from '@/lib/cn'

interface BadgeProps {
  children: React.ReactNode
  style?: React.CSSProperties
  className?: string
  size?: 'sm' | 'md'
}

export function Badge({ children, style, className, size = 'sm' }: BadgeProps) {
  return (
    <span
      style={style}
      className={cn(
        'inline-flex items-center font-medium rounded-full border',
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm',
        className
      )}
    >
      {children}
    </span>
  )
}
