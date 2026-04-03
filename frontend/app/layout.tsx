import type { Metadata } from 'next'
import './globals.css'
import { Sidebar } from '@/components/layout/Sidebar'
import { Header } from '@/components/layout/Header'

export const metadata: Metadata = {
  title: 'StockAgent — 자동매매 대시보드',
  description: '미국-한국 주식 연계 자동매매 시스템 모니터링',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ko">
      <body className="bg-[#0a0a0f] text-[#f0f0f8]">
        <Sidebar />
        <Header />
        <main
          className="min-h-screen pt-16 transition-all duration-200"
          style={{ paddingLeft: '240px' }}
        >
          <div className="p-6">
            {children}
          </div>
        </main>
      </body>
    </html>
  )
}
