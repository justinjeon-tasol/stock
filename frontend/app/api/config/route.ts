import { NextRequest, NextResponse } from 'next/server'
import { readFile, writeFile } from 'fs/promises'
import path from 'path'

const CONFIG_PATH = path.join(process.cwd(), '..', 'config', 'strategy_config.json')

async function readConfig() {
  const content = await readFile(CONFIG_PATH, 'utf-8')
  return JSON.parse(content)
}

export async function GET() {
  try {
    return NextResponse.json(await readConfig())
  } catch {
    return NextResponse.json({ error: '설정 파일 읽기 실패' }, { status: 500 })
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const updates = await req.json()
    const config = await readConfig()

    // 허용된 경로만 업데이트 (보안: 임의 필드 덮어쓰기 방지)
    const ALLOWED_PATHS: string[] = [
      'risk_management.max_stock_weight_pct',
      'recommendation_rules.max_stocks',
      'recommendation_rules.min_confidence',
      'recommendation_rules.futures_threshold_pct',
      'phase_weights.대상승장.cash',
      'phase_weights.상승장.cash',
      'phase_weights.일반장.cash',
      'phase_weights.변동폭큰.cash',
      'phase_weights.하락장.cash',
      'phase_weights.대폭락장.cash',
    ]

    for (const [dotPath, value] of Object.entries(updates)) {
      if (!ALLOWED_PATHS.includes(dotPath)) continue
      const keys = dotPath.split('.')
      let obj: Record<string, unknown> = config
      for (let i = 0; i < keys.length - 1; i++) {
        obj = obj[keys[i]] as Record<string, unknown>
      }
      obj[keys[keys.length - 1]] = value

      // phase_weights 수정 시 aggressive 자동 재계산 (cash 변경 → aggressive = 1 - cash - defensive)
      if (dotPath.startsWith('phase_weights.') && dotPath.endsWith('.cash')) {
        const phase = keys[1]
        const pw = config.phase_weights[phase]
        pw.aggressive = Math.max(0, Math.round((1 - pw.cash - pw.defensive) * 100) / 100)
      }
    }

    await writeFile(CONFIG_PATH, JSON.stringify(config, null, 2), 'utf-8')
    return NextResponse.json({ ok: true, config })
  } catch {
    return NextResponse.json({ error: '설정 저장 실패' }, { status: 500 })
  }
}
