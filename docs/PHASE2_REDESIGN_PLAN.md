# 2단계 재설계 계획서

> **검색 키워드**: 2단계, 재설계, Phase2, REDESIGN, 전략전술트리
> **작성일**: 2026-04-16
> **상태**: 보류 (1단계 핫픽스 완료 후 진행)

---

## 관련 파일 목록

| 파일 | 위치 | 용도 |
|------|------|------|
| 전략/전술 트리 (전체) | `docs/PHASE2_REDESIGN_PLAN.md` | 이 파일 |
| 매매 분석 데이터 | `/tmp/trades_dump.json` | trades 157건, positions 97건 |
| 기존 수정 이력 | `FIX_LOG_20260413.md` | 이전 버그 수정 11건 |
| 기존 수정 프롬프트 | `FIX_PROMPT.md` | FIX-1~17 상세 |
| Claude 계획 파일 | `.claude/plans/clever-finding-feigenbaum.md` | 상세 트리 |

---

## 1단계 핫픽스 (선행 완료 필요)

즉시 적용 3건 (기존 로직 최소 변경, +10~15%p 개선 기대):

1. **추격매수 방지 24시간 제한**: `executor.py` L1680 부근
2. **SIGNAL_EXIT 초단기만 허용**: `position_manager.py` L229 부근
3. **중기 포지션 REDUCE 면제**: `weight_adjuster.py` L247 부근

---

## 2단계 재설계 범위

### 새 파이프라인 (8단계)

```
Phase 1.   시장 분석 (국면 판단, 시장 추세)
Phase 2.   전략 선택 (초단기/단기/중기/중장기 + 매매계획 확정)
Phase 2.5  유니버스 사전 스캔 (전체 종목 주가흐름/추세 경량 분석)
Phase 3.   테마/종목군 선정 (선행지표 → 섹터 → 종목 풀)
Phase 4.   개별 종목 선택 (상세 분석 + 전략 매칭 확인 + 차단 조건)
Phase 5.   매수 실행 (Plan-Your-Trade, exit_plan 부착)
Phase 6.   보유 관리 (장 전 재평가 + 장중 모니터링 + 파샬 관리)
Phase 7.   청산 관리 (Exit Manager, 단일 우선순위 P1~P6)
Phase 8.   리스크 관리 (DSL/WSL, 포지션 한도)
```

### 핵심 변경사항

1. **전략별 독립 JSON 파일** (`config/tactics/`)
   - ultra_short.json, short_term.json, mid_term.json, long_term.json
   - 각 전략에 entry/exit/risk 파라미터 완전 정의
   - 백테스팅 결과 자동 반영 (performance 섹션)

2. **Exit Manager** (`agents/exit_manager.py` 신규)
   - executor.py에서 청산 로직 분리
   - 단일 우선순위 P1~P6 체계
   - 전략별 청산 행동 매트릭스

3. **Plan-Your-Trade**
   - 매수 전에 전략 유형별 exit_plan 완전 확정
   - weight_adjuster.py에서 exit_plan 생성까지 통합
   - 현재: 매수 후 사후 생성 → 변경: 매수 전 사전 확정

4. **분할(파샬) 보유 관리**
   - 같은 종목 복수 전략으로 분리 보유
   - positions 테이블에 strategy_type 컬럼 추가
   - 각 파샬은 독립 exit_plan

5. **장 시작 전 재평가 (Pre-Market Review)**
   - 08:30~09:00 보유 포지션 그룹핑 재조정
   - 국면 변화 → 전략 전환 → exit_plan 재생성

6. **유니버스 사전 스캔 (Phase 2.5)**
   - 전체 종목 주가흐름/추세 경량 분석 + 캐싱
   - 전략별 적합 종목 사전 분류

7. **종목별 상세 분석 (Phase 4 확장)**
   - 지지/저항선, 채널 분석, 거래량 프로파일
   - 칼만 필터 기반 예상추세, 선행지표 lag 반영
   - forecast 등급 (STRONG_UP / UP / FLAT / DOWN)

### 수정 대상 파일

| 파일 | 변경 유형 | 작업 |
|------|----------|------|
| `agents/exit_manager.py` | **신규** | Exit Manager (executor에서 청산 로직 이전) |
| `config/tactics/*.json` | **신규** | 4가지 전략 파일 |
| `agents/executor.py` | 대폭 수정 | 청산 로직 위임, BUY시 전략 부착 |
| `agents/weight_adjuster.py` | 확장 | Tactic Planner 역할, exit_plan 사전 생성 |
| `orchestrator.py` | 수정 | 파이프라인 재배치, Pre-Market Review 추가 |
| `agents/position_manager.py` | 수정 | 파샬 관리, 전략 변경 시 exit_plan 연동 |
| `agents/market_analyzer.py` | 확장 | 유니버스 사전 스캔, 종목 상세 분석 |
| `main.py` | 수정 | Pre-Market Review 모드 추가 |

---

## 전략별 매매계획 요약

| 항목 | 초단기 | 단기 | 중기 | 중장기 |
|------|--------|------|------|--------|
| 보유기간 | ~당일 | 1~5일 | 5~20일 | 20~90일 |
| 종목당 비중 | 10% | 15~20% | 15~25% | 20~30% |
| TP1 | +1.0% (50%) | +3% (30%) | +5% (20%) | +8% (20%) |
| TP2 | +1.5% (전량) | +7% (30%) | +10% (30%) | +15% (20%) |
| 트레일링 | 없음 | +3% 활성, -1.5% | +5% 활성, -2.5% | +8% 활성, -4% |
| SL | -1.5% | -3% | -5% | -5% |
| 보호시간 | 30분 | 2시간 | 6시간 | 24시간 |
| SIGNAL_EXIT | 허용 | 차단 | 차단 | 차단 |
| REDUCE | 차단 | 허용 | 차단 | 차단 |
| 최대 종목수 | 2 | 3~4 | 3~5 | 3 |

---

## 분석 결과 요약 (근거 데이터)

16일 운영 결과 (2026-04-01~04-16):
- 누적: -36.95%, MDD -56%, 승률 33%
- 60%가 1시간 내 청산 (승률 21.8%)
- TRAILING_STOP: 11건, 100% 승률, +29.25% (유일한 수익원)
- SIGNAL_EXIT: 25건, 승률 20%, -9.23% (해로움)
- STOP_LOSS: 13건, -59.10% (치명적)
- 중기 승률 67% vs 단기 25% → 중기 비중 확대 필요
- 보유 3시간+ 승률 63% vs 1시간 이내 21.8% → 보유시간 확보 필요

---

## 검증 방법
1. 과거 157건 trades에 대해 TO-BE 로직 시뮬레이션
2. main에서 모의투자 1주일 운영 후 성과 비교 (별도 Supabase 불필요)
3. 핵심 메트릭: 승률, 평균 보유시간, 중기 조기청산 비율, TRAILING_STOP 도달률
