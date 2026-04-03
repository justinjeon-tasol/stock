'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, Minus, BarChart3, Target, Zap } from 'lucide-react'
import { formatKRW } from '@/lib/format'

function fmtNum(n: number): string {
  return Math.round(n).toLocaleString('ko-KR')
}

interface Report {
  generated_at: string
  backtest: {
    total_signals: number
    unique_stocks: number
    avg_win_rate: number
    avg_return: number
    indicator_ranking: Array<{
      indicator: string; stocks: number; avg_win_rate: number;
      avg_return: number; total_edge: number; total_trades: number
    }>
    top_strategies: Array<{
      code: string; name: string; indicator: string; threshold: number;
      direction: string; win_rate: number; avg_return: number; trades: number; edge: number
    }>
  }
  correlation: {
    top_leading_indicators: Array<{
      indicator: string; category: string; lag_0: number; lag_1: number; observations: number
    }>
    vix_regime: Array<{
      vix_range: string; days: number; mean_ret: number; win_rate: number
    }>
    stock_us_correlation: Array<{
      kr_stock: string; us_indicator: string; lag_1: number
    }>
  }
  live_performance: {
    trade_count: number; buy_count: number; sell_count: number;
    win_rate: number; total_pnl_pct: number; period_days: number
    strategy_performance: Array<{
      strategy_id: string; trades: number; win_rate: number; total_pnl: number
    }>
  }
  active_strategies: Array<{
    id: string; phase: string; status: string; win_rate: number;
    return_pct: number; mdd: number; trade_count: number
  }>
  exit_plans: Array<{
    code: string; name: string; trend: string;
    target_1w: number; target_1m: number; confidence: number;
    avg_price: number; current_price: number; pnl_pct: number;
    quantity: number; holding_period: string;
    stage_count: number;
    stages: Array<{
      stage: number; type: string; trigger_price: number;
      trigger_vs_avg: number; sell_ratio: number; status: string; rationale: string;
    }>;
    sl_price: number; sl_pct: number;
    upside_p75: number | null; upside_p90: number | null;
  }>
}

type TabType = 'overview' | 'indicators' | 'strategies' | 'positions'

export default function StrategyPage() {
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<TabType>('overview')

  const fetchReport = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/strategy-report')
      if (res.ok) setReport(await res.json())
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetchReport() }, [fetchReport])

  if (loading) return <p className="text-xs text-[#555570] py-8 text-center">리포트 로드 중...</p>
  if (!report) return <p className="text-xs text-[#f87171] py-8 text-center">리포트를 불러올 수 없습니다</p>

  const bt = report.backtest
  const live = report.live_performance
  const corr = report.correlation

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[#f0f0f8]">전략 리포트</h1>
          <p className="text-xs text-[#555570] mt-0.5">
            {report.generated_at?.slice(0, 10)} 기준 — 30년 백테스팅 + 실매매 분석
          </p>
        </div>
        <button onClick={fetchReport}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-[#1e1e2a] text-[#8888a8] hover:text-[#f0f0f8] transition-colors">
          <RefreshCw className="w-3 h-3" /> 새로고침
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#2a2a38]">
        {([
          { key: 'overview' as TabType, label: '종합', icon: BarChart3 },
          { key: 'indicators' as TabType, label: '선행지표', icon: Zap },
          { key: 'strategies' as TabType, label: '전략', icon: Target },
          { key: 'positions' as TabType, label: '매도계획', icon: TrendingUp },
        ]).map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors relative ${
              tab === t.key ? 'text-[#f0f0f8]' : 'text-[#555570] hover:text-[#8888a8]'
            }`}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
            {tab === t.key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#60a5fa]" />}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <SummaryCard label="백테스트 시그널" value={`${bt?.total_signals?.toLocaleString() ?? 0}건`} sub={`${bt?.unique_stocks ?? 0}종목`} />
            <SummaryCard label="백테스트 승률" value={`${bt?.avg_win_rate ?? 0}%`} sub={`수익 ${bt?.avg_return ?? 0}%`} positive={(bt?.avg_win_rate ?? 0) > 55} />
            <SummaryCard label="실매매 거래" value={`${live?.trade_count ?? 0}건`} sub={`${live?.period_days ?? 0}일간`} />
            <SummaryCard label="실매매 승률" value={`${live?.win_rate ?? 0}%`} sub={`손익 ${live?.total_pnl_pct ?? 0}%`} positive={(live?.total_pnl_pct ?? 0) > 0} />
          </div>

          {/* VIX Regime */}
          {corr?.vix_regime && (
            <div>
              <h3 className="text-sm font-medium text-[#8888a8] mb-2">VIX 구간별 KOSPI 수익률 (20년)</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#2a2a38]">
                      {['VIX 구간', '관측일', '평균수익', '승률'].map(h => (
                        <th key={h} className="text-left text-xs text-[#555570] py-2 px-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {corr.vix_regime.map((v) => (
                      <tr key={v.vix_range} className="border-b border-[#1e1e2a]">
                        <td className="py-2 px-3 text-[#f0f0f8] text-xs">{v.vix_range}</td>
                        <td className="py-2 px-3 text-[#8888a8] text-xs">{v.days}일</td>
                        <td className="py-2 px-3 text-xs font-mono" style={{ color: v.mean_ret > 0 ? '#4ade80' : '#f87171' }}>
                          {v.mean_ret > 0 ? '+' : ''}{v.mean_ret}%
                        </td>
                        <td className="py-2 px-3 text-xs font-mono" style={{ color: v.win_rate > 52 ? '#4ade80' : '#f87171' }}>
                          {v.win_rate}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'indicators' && (
        <>
          <h3 className="text-sm font-medium text-[#8888a8]">선행지표 순위 (30년 백테스팅 기준)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a38]">
                  {['순위', '지표', '유효종목', '평균승률', '평균수익', '총기대값', '거래수'].map(h => (
                    <th key={h} className="text-left text-xs text-[#555570] py-2 px-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bt?.indicator_ranking?.map((r, i) => (
                  <tr key={r.indicator} className="border-b border-[#1e1e2a] hover:bg-[#1a1a24]">
                    <td className="py-2.5 px-3 text-xs text-[#555570]">{i + 1}</td>
                    <td className="py-2.5 px-3 text-[#f0f0f8] text-xs font-medium">{r.indicator}</td>
                    <td className="py-2.5 px-3 text-xs text-[#8888a8]">{r.stocks}</td>
                    <td className="py-2.5 px-3 text-xs font-mono" style={{ color: r.avg_win_rate > 57 ? '#4ade80' : '#8888a8' }}>
                      {r.avg_win_rate}%
                    </td>
                    <td className="py-2.5 px-3 text-xs font-mono text-[#4ade80]">+{r.avg_return}%</td>
                    <td className="py-2.5 px-3 text-xs font-mono text-[#fbbf24]">{fmtNum(r.total_edge)}</td>
                    <td className="py-2.5 px-3 text-xs text-[#555570]">{fmtNum(r.total_trades)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 종목-US 상관관계 */}
          {corr?.stock_us_correlation && (
            <div className="mt-6">
              <h3 className="text-sm font-medium text-[#8888a8] mb-2">종목별 최적 US 연동 지표</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {corr.stock_us_correlation.map((s) => (
                  <div key={s.kr_stock} className="bg-[#13131a] border border-[#2a2a38] rounded-lg p-3">
                    <p className="text-xs text-[#f0f0f8] font-medium">{s.kr_stock}</p>
                    <p className="text-xs text-[#8888a8] mt-1">→ {s.us_indicator}</p>
                    <p className="text-xs font-mono mt-0.5" style={{ color: s.lag_1 > 0.2 ? '#4ade80' : '#8888a8' }}>
                      상관계수: {s.lag_1 > 0 ? '+' : ''}{s.lag_1}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'strategies' && (
        <>
          <h3 className="text-sm font-medium text-[#8888a8]">전략 목록</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a38]">
                  {['전략ID', '국면', '상태', '승률', '수익률', 'MDD', '거래수'].map(h => (
                    <th key={h} className="text-left text-xs text-[#555570] py-2 px-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.active_strategies.map((s) => (
                  <tr key={s.id} className="border-b border-[#1e1e2a]">
                    <td className="py-2.5 px-3 text-xs text-[#f0f0f8] font-medium">{s.id}</td>
                    <td className="py-2.5 px-3 text-xs text-[#8888a8]">{s.phase}</td>
                    <td className="py-2.5 px-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        s.status === '검증완료' ? 'bg-[#052e16] text-[#4ade80]' :
                        s.status === '비활성' ? 'bg-[#450a0a] text-[#f87171]' :
                        'bg-[#1e1e2a] text-[#8888a8]'
                      }`}>{s.status}</span>
                    </td>
                    <td className="py-2.5 px-3 text-xs font-mono" style={{ color: s.win_rate > 55 ? '#4ade80' : '#8888a8' }}>
                      {s.win_rate}%
                    </td>
                    <td className="py-2.5 px-3 text-xs font-mono" style={{ color: s.return_pct > 0 ? '#4ade80' : '#f87171' }}>
                      {s.return_pct > 0 ? '+' : ''}{s.return_pct}%
                    </td>
                    <td className="py-2.5 px-3 text-xs font-mono text-[#f87171]">{s.mdd}%</td>
                    <td className="py-2.5 px-3 text-xs text-[#555570]">{s.trade_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 실매매 전략별 성과 */}
          {live?.strategy_performance && live.strategy_performance.length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-medium text-[#8888a8] mb-2">실매매 전략별 성과</h3>
              {live.strategy_performance.map((sp) => (
                <div key={sp.strategy_id} className="flex items-center gap-4 py-2 border-b border-[#1e1e2a]">
                  <span className="text-xs text-[#f0f0f8] w-20">{sp.strategy_id}</span>
                  <span className="text-xs text-[#8888a8]">{sp.trades}건</span>
                  <span className="text-xs font-mono" style={{ color: sp.win_rate > 50 ? '#4ade80' : '#f87171' }}>
                    승률 {sp.win_rate}%
                  </span>
                  <span className="text-xs font-mono" style={{ color: sp.total_pnl > 0 ? '#4ade80' : '#f87171' }}>
                    {sp.total_pnl > 0 ? '+' : ''}{sp.total_pnl}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === 'positions' && (
        <>
          <h3 className="text-sm font-medium text-[#8888a8]">보유종목 매도 계획 (Exit Plan)</h3>
          {report.exit_plans.length === 0 ? (
            <p className="text-xs text-[#555570] py-8 text-center">활성 매도 계획 없음</p>
          ) : (
            <div className="space-y-4">
              {report.exit_plans.map((p) => {
                const trendColor = p.trend?.includes('PROFIT') ? '#4ade80' :
                  p.trend === 'RECOVERING' ? '#fbbf24' : p.trend === 'LOSS_ZONE' ? '#f87171' : '#8888a8'
                const trendLabel = p.trend === 'PROFIT_UP' ? '수익+상승' :
                  p.trend === 'PROFIT_FLAT' ? '수익+횡보' :
                  p.trend === 'RECOVERING' ? '회복중' :
                  p.trend === 'LOSS_ZONE' ? '손실구간' : p.trend
                return (
                  <div key={p.code} className="bg-[#13131a] border border-[#2a2a38] rounded-lg p-4 space-y-3">
                    {/* Header */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-[#f0f0f8] font-medium">{p.name}</span>
                        <span className="text-xs text-[#555570]">{p.code}</span>
                        <span className="text-xs text-[#555570]">{p.quantity}주 / {p.holding_period}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {p.trend?.includes('PROFIT') ? <TrendingUp className="w-4 h-4" style={{ color: trendColor }} /> :
                         p.trend === 'LOSS_ZONE' ? <TrendingDown className="w-4 h-4" style={{ color: trendColor }} /> :
                         <Minus className="w-4 h-4" style={{ color: trendColor }} />}
                        <span className="text-xs font-medium" style={{ color: trendColor }}>{trendLabel}</span>
                      </div>
                    </div>

                    {/* Price Info */}
                    <div className="grid grid-cols-4 gap-3 text-xs">
                      <div>
                        <p className="text-[#555570]">매입가</p>
                        <p className="font-mono text-[#8888a8]">{p.avg_price ? formatKRW(p.avg_price) : '-'}</p>
                      </div>
                      <div>
                        <p className="text-[#555570]">현재가</p>
                        <p className="font-mono" style={{ color: p.pnl_pct >= 0 ? '#4ade80' : '#f87171' }}>
                          {p.current_price ? formatKRW(p.current_price) : '-'} ({p.pnl_pct >= 0 ? '+' : ''}{p.pnl_pct}%)
                        </p>
                      </div>
                      <div>
                        <p className="text-[#555570]">1주 목표</p>
                        <p className="font-mono text-[#8888a8]">{p.target_1w ? formatKRW(p.target_1w) : '-'}</p>
                      </div>
                      <div>
                        <p className="text-[#555570]">1개월 목표</p>
                        <p className="font-mono text-[#8888a8]">{p.target_1m ? formatKRW(p.target_1m) : '-'}</p>
                      </div>
                    </div>

                    {/* Upside + SL */}
                    <div className="grid grid-cols-4 gap-3 text-xs">
                      <div>
                        <p className="text-[#555570]">상승여력(75%ile)</p>
                        <p className="font-mono text-[#4ade80]">{p.upside_p75 != null ? `+${p.upside_p75}%` : '-'}</p>
                      </div>
                      <div>
                        <p className="text-[#555570]">최대기대(90%ile)</p>
                        <p className="font-mono text-[#4ade80]">{p.upside_p90 != null ? `+${p.upside_p90}%` : '-'}</p>
                      </div>
                      <div>
                        <p className="text-[#555570]">손절가</p>
                        <p className="font-mono text-[#f87171]">{p.sl_price ? formatKRW(p.sl_price) : '-'} ({p.sl_pct}%)</p>
                      </div>
                      <div>
                        <p className="text-[#555570]">신뢰도</p>
                        <p className="font-mono text-[#8888a8]">{((p.confidence ?? 0) * 100).toFixed(0)}%</p>
                      </div>
                    </div>

                    {/* Exit Stages */}
                    {p.stages && p.stages.length > 0 && (
                      <div className="border-t border-[#2a2a38] pt-2">
                        <p className="text-xs text-[#555570] mb-1.5">매도 단계</p>
                        <div className="space-y-1">
                          {p.stages.map((s) => (
                            <div key={s.stage} className="flex items-center gap-3 text-xs">
                              <span className="w-14 text-[#555570]">Stage {s.stage}</span>
                              <span className={`w-12 px-1.5 py-0.5 rounded text-center ${
                                s.status === 'EXECUTED' ? 'bg-[#052e16] text-[#4ade80]' :
                                s.status === 'PENDING' ? 'bg-[#1e1e2a] text-[#8888a8]' : 'bg-[#1e1e2a] text-[#555570]'
                              }`}>{s.status === 'EXECUTED' ? '완료' : '대기'}</span>
                              <span className="font-mono text-[#f0f0f8]">{formatKRW(s.trigger_price)}</span>
                              <span className="font-mono" style={{ color: s.trigger_vs_avg >= 0 ? '#4ade80' : '#f87171' }}>
                                (매입{s.trigger_vs_avg >= 0 ? '+' : ''}{s.trigger_vs_avg}%)
                              </span>
                              <span className="text-[#555570]">{(s.sell_ratio * 100).toFixed(0)}% 매도</span>
                              <span className="text-[#555570] truncate">{s.rationale}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function SummaryCard({ label, value, sub, positive }: {
  label: string; value: string; sub: string; positive?: boolean
}) {
  return (
    <div className="bg-[#13131a] border border-[#2a2a38] rounded-lg p-4">
      <p className="text-xs text-[#555570] mb-1">{label}</p>
      <p className="text-base font-semibold" style={{
        color: positive === undefined ? '#f0f0f8' : positive ? '#4ade80' : '#f87171'
      }}>{value}</p>
      <p className="text-xs text-[#555570] mt-0.5">{sub}</p>
    </div>
  )
}
