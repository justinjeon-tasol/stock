import { NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import path from 'path'

export async function GET() {
  try {
    const reportPath = path.join(process.cwd(), '..', 'data', 'reports', 'strategy_report.json')
    const content = await readFile(reportPath, 'utf-8')
    return NextResponse.json(JSON.parse(content))
  } catch {
    return NextResponse.json({ error: '리포트 파일 없음' }, { status: 404 })
  }
}

export const dynamic = 'force-dynamic'
