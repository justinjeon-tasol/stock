import type { AgentCode, AgentMeta } from './types'

export const AGENT_META: Record<AgentCode, AgentMeta> = {
  OR: {
    code: 'OR',
    name: '오케스트레이터',
    file: 'orchestrator.py',
    layer: '지휘',
    description: '5단계 파이프라인 제어, 백테스팅 트리거, 최종 판단',
  },
  DC: {
    code: 'DC',
    name: '데이터수집',
    file: 'data_collector.py',
    layer: '데이터',
    description: '미국/한국/원자재/뉴스 수집 + 전처리',
  },
  MA: {
    code: 'MA',
    name: '시장분석',
    file: 'market_analyzer.py',
    layer: '전략',
    description: '국면감지 + 선행지표 + 이슈감지 통합 분석',
  },
  WA: {
    code: 'WA',
    name: '가중치조정',
    file: 'weight_adjuster.py',
    layer: '전략',
    description: '국면+이슈 반영한 전략 비중 자동 재배분',
  },
  SR: {
    code: 'SR',
    name: '전략엔진',
    file: 'strategy_researcher.py',
    layer: '전략',
    description: '전략 적용 + 백테스팅 + 자동 비활성화',
  },
  EX: {
    code: 'EX',
    name: '실행',
    file: 'executor.py',
    layer: '전략',
    description: 'KIS API 주문, 손절/익절, DCA, 분할매도',
  },
  DB: {
    code: 'DB',
    name: '모니터링',
    file: 'debugger.py',
    layer: '운영',
    description: '24시간 감시 + 시스템 헬스 분석 + 설정 패치',
  },
}

export const AGENT_CODES: AgentCode[] = ['OR', 'DC', 'MA', 'WA', 'SR', 'EX', 'DB']
