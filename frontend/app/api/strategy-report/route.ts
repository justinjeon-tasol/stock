import { NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import path from 'path'

export async function GET() {
  // 1순위: frontend/public/data/strategy_report.json (Vercel 배포용)
  // 2순위: ../data/reports/strategy_report.json (GCP VM 로컬)
  const candidates = [
    path.join(process.cwd(), 'public', 'data', 'strategy_report.json'),
    path.join(process.cwd(), '..', 'data', 'reports', 'strategy_report.json'),
  ]

  for (const reportPath of candidates) {
    try {
      const content = await readFile(reportPath, 'utf-8')
      return NextResponse.json(JSON.parse(content))
    } catch {
      continue
    }
  }

  return NextResponse.json({ error: '리포트 파일 없음' }, { status: 404 })
}

export const dynamic = 'force-dynamic'
