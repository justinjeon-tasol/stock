'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Briefcase,
  ArrowLeftRight,
  Bot,
  Settings,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  BarChart2,
} from 'lucide-react'
import { cn } from '@/lib/cn'

const NAV_ITEMS = [
  { href: '/',          icon: LayoutDashboard,  label: '대시보드' },
  { href: '/positions', icon: Briefcase,         label: '포지션' },
  { href: '/trades',    icon: ArrowLeftRight,    label: '매매이력' },
  { href: '/account',   icon: BarChart2,         label: '계좌내역' },
  { href: '/strategy',  icon: TrendingUp,        label: '전략리포트' },
  { href: '/agents',    icon: Bot,               label: '에이전트' },
  { href: '/settings',  icon: Settings,          label: '설정' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const pathname = usePathname()

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-full z-40 flex flex-col',
        'bg-[#111118] border-r border-[#2a2a38]',
        'transition-all duration-200 ease-in-out',
        collapsed ? 'w-[60px]' : 'w-[240px]'
      )}
    >
      {/* 로고 */}
      <div className="flex items-center h-16 px-4 border-b border-[#2a2a38] shrink-0">
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="w-8 h-8 rounded-lg bg-[#7c6af7] flex items-center justify-center shrink-0">
            <TrendingUp className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <span className="text-sm font-bold text-[#f0f0f8] whitespace-nowrap">
              StockAgent
            </span>
          )}
        </div>
      </div>

      {/* 네비게이션 */}
      <nav className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-2">
          {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
            const isActive = pathname === href
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg',
                    'text-sm font-medium transition-colors duration-100',
                    isActive
                      ? 'bg-[#7c6af7]/20 text-[#7c6af7]'
                      : 'text-[#8888a8] hover:text-[#f0f0f8] hover:bg-[#1a1a24]'
                  )}
                  title={collapsed ? label : undefined}
                >
                  <Icon className="w-5 h-5 shrink-0" />
                  {!collapsed && <span className="truncate">{label}</span>}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* 접기/펼치기 버튼 */}
      <div className="p-2 border-t border-[#2a2a38] shrink-0">
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={cn(
            'w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg',
            'text-[#555570] hover:text-[#8888a8] hover:bg-[#1a1a24]',
            'text-xs transition-colors duration-100'
          )}
          title={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <>
              <ChevronLeft className="w-4 h-4" />
              <span>접기</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
