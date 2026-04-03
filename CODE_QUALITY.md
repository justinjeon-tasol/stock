# 코드 품질 하네스
> 마지막 업데이트: 2026-03-30
> 대상: agents/, protocol/, orchestrator.py, main.py, report_generator.py

심각도 기준: 🔴 심각 (즉시 수정) / 🟡 주의 (다음 스프린트) / 🟢 개선권장 (여유 시)

---

## 전체 현황

| 심각도 | 건수 | 처리 |
|--------|------|------|
| 🔴 심각 | 3건 | [x] 3/3 완료 (2026-03-30) |
| 🟡 주의 | 18건 | [ ] 0/18 |
| 🟢 개선권장 | 15건 | [ ] 0/15 |

---

## 파일별 이슈

### protocol/protocol.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| P-1 | 🟡 | 176~179 | `from_dict()` 복원 시 `__post_init__` 덮어쓰기 방지 로직이 불명확 | `msg_id`/`timestamp` 이미 설정 여부 체크하는 플래그 추가 | [ ] |
| P-2 | 🟢 | 36~42 | `dataclass_to_dict()`가 튜플 입력에 list 반환 → 타입 손실 | `isinstance(obj, tuple)` 시 `tuple(...)` 반환 | [ ] |
| P-3 | 🟢 | 78~80 | `VALID_PRIORITIES`, `VALID_MSG_TYPES` 정의만 있고 검증 안 함 | `__post_init__`에서 유효성 검증 추가 | [ ] |

---

### agents/base_agent.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| B-1 | 🟡 | 234 | 재시도 대기 `0.5 * attempt` — 최대 상한 없음 | `min(0.5 * attempt, 3.0)` 으로 상한 제한 | [ ] |

---

### agents/data_collector.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| D-1 | 🔴 | 47, 50, 53, 202 | `self.log("ERROR", ...)` 대문자 사용 — 전체 에이전트 규약과 불일치 | `self.log("error", ...)` 소문자로 통일 | [x] 2026-03-30 |
| D-2 | 🟡 | 75~76, 211~212 | `asyncio.get_event_loop()` — Python 3.10+에서 `None` 반환 가능 | `asyncio.to_thread()` 또는 `asyncio.get_running_loop()` 로 교체 | [ ] |
| D-3 | 🟡 | 113~115 | 데이터 부재 시 기본값 0.0 반환 — 실제 0값과 구분 불가 | 데이터 상태 플래그 필드 추가 (`data_valid: bool`) | [ ] |
| D-4 | 🟢 | 18 | `FUTURES_THRESHOLD = 0.3` 하드코딩 | `config/strategy_config.json` 에서 로드 | [ ] |

---

### agents/preprocessor.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| PR-1 | 🟡 | 44 | `body.get("payload", {})` — payload가 리스트일 경우 미처리 | 명시적 `isinstance(payload, dict)` 체크 추가 | [ ] |
| PR-2 | 🟢 | 23 | `ANOMALY_THRESHOLD = 15.0` 하드코딩 | `config/strategy_config.json` 에서 로드 | [ ] |

---

### agents/market_analyzer.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| MA-1 | 🟡 | 161~164 | `or 0.0` 연산 — `0.0`은 falsy라서 의도와 다르게 동작 가능 | `if val is None: val = 0.0` 명시적 None 체크로 교체 | [ ] |
| MA-2 | 🟡 | 238~248 | MA-1 동일 패턴 반복 (`or 0.0`) | 위와 동일 | [ ] |
| MA-3 | 🟢 | 22~91 | 모든 기준값/매핑이 클래스 변수로 하드코딩 | `config/strategy_config.json` 에서 로드하는 방식으로 전환 | [ ] |

---

### agents/weight_adjuster.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| WA-1 | 🟡 | 182 | `_phase_weights`가 비어있으면 `float()` 변환 시 KeyError 가능 | `_FALLBACK_PHASE_WEIGHTS` 직접 참조로 변경 | [ ] |
| WA-2 | 🟡 | 292 | `"전반"` 섹터 처리 로직이 불명확 — 의도가 코드에서 안 보임 | 주석 보강 또는 별도 메서드 분리 | [ ] |
| WA-3 | 🟡 | 315 | 중복 종목의 weight 누적이 의도인지 불명확 | 동작 명확히 주석 처리, 또는 누적 대신 최대값 선택 | [ ] |
| WA-4 | 🟡 | 163 | `msg.body["payload"]` 직접 수정 — 메시지 불변성 위반 | `StandardMessage` 재생성 방식으로 변경 | [ ] |
| WA-5 | 🟢 | 46~50 | `_CONFIG_PATH` 계산에 `os.path` 사용 — `Path` 방식과 혼재 | `Path(__file__).parent.parent` 방식으로 통일 | [ ] |

---

### agents/executor.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| EX-1 | 🔴 | 127 | `raise_for_status()` 예외 처리 없음 — HTTP 오류 시 파이프라인 전체 중단 | `try/except requests.exceptions.RequestException` 으로 감싸기 | [x] 2026-03-30 |
| EX-2 | 🔴 | 200~201 | `_place_order()`에서 동일 문제 (`raise_for_status()` 예외 처리 부재) | EX-1과 동일하게 처리 | [x] 2026-03-30 (이미 처리됨 확인) |
| EX-3 | 🟡 | 356~364 | 토큰 발급 실패 시 모든 targets에 ERROR 상태 반복 — 토큰 재시도 없음 | 토큰 재시도 후 실패 시 전체 SKIP 처리 | [ ] |
| EX-4 | 🟡 | 385 | `buy_results` 변수명이지만 SKIP 제외 로직 — 조건 재검토 필요 | 변수명을 `notify_results`로 변경하거나 조건 명확화 | [ ] |
| EX-5 | 🟡 | 409 | `msg.body["payload"]` 직접 수정 — WA-4와 동일 문제 | WA-4와 동일하게 처리 | [ ] |
| EX-6 | 🟢 | 20, 24, 27 | KIS API URL, TR ID 하드코딩 | `config/api_config.json` 으로 분리 | [ ] |
| EX-7 | 🟢 | 188 | 주문 수량 1주 고정 — 추후 weight 기반 수량 조정 불가 | weight → 수량 변환 로직 설계 필요 (실전 전환 전) | [ ] |

---

### agents/recommender.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| RC-1 | 🟡 | 115 | `confidence = 0`일 때 후보 절반 제한 — 의도 불명확 | 조건 검토 후 주석 또는 분기 명확화 | [ ] |
| RC-2 | 🟡 | 203~204 | 신뢰도 기반 후보 제한이 정렬 전에 발생 — 약한 후보가 살아남을 수 있음 | 정렬 → 상위 선택 → 신뢰도 기반 제한 순서로 변경 | [ ] |

---

### orchestrator.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| OR-1 | 🟡 | 68~76 | Step 1 실패 시 즉시 반환 — graceful degradation 없음 | 기본값 데이터로 계속 진행하는 fallback 추가 | [ ] |
| OR-2 | 🟡 | 130 | `step4_result` None 체크 누락 가능성 | 명시적 `if step4_result is None` 체크 추가 | [ ] |
| OR-3 | 🟡 | 199~204 | `run_scheduled()` 내 중첩 KeyboardInterrupt 미처리 | 중첩 try-except 추가 | [ ] |

---

### report_generator.py

| # | 심각도 | 라인 | 문제 | 개선 방향 | 처리 |
|---|--------|------|------|-----------|------|
| RG-1 | 🟡 | 256 | 한글 정렬에 `len()` 사용 — 2바이트 문자로 출력 폭이 어긋남 | `unicodedata.east_asian_width()` 기반 폭 계산으로 교체 | [ ] |

---

## 교차 파일 공통 이슈

### 🔴 심각

| # | 문제 | 영향 파일 | 개선 방향 |
|---|------|----------|-----------|
| X-1 | HTTP 예외 처리 일관성 부재 — 오류 처리 강도가 파일마다 다름 | executor.py | 공통 HTTP 유틸리티 함수 `utils/http_client.py` 작성 |

### 🟡 주의

| # | 문제 | 영향 파일 | 개선 방향 |
|---|------|----------|-----------|
| X-2 | `asyncio.get_event_loop()` 구식 패턴 | data_collector.py, executor.py | `asyncio.to_thread()` 로 통일 |
| X-3 | `msg.body["payload"]` 직접 수정 — 메시지 불변성 위반 | weight_adjuster.py, executor.py | StandardMessage 재생성 방식으로 통일 |
| X-4 | None vs 0.0 구분 불가 — `or 0.0` 패턴 | market_analyzer.py | 명시적 None 체크로 전면 교체 |
| X-5 | 로그 레벨 대소문자 불일치 | data_collector.py | 전체 소문자로 통일 |

### 🟢 개선권장

| # | 문제 | 개선 방향 |
|---|------|-----------|
| X-6 | 설정값 분산 — 각 파일마다 하드코딩 또는 다른 방식으로 config 로드 | `config/agent_config.json` 도입 (timeout, max_retries, 임계값) |
| X-7 | KIS API 설정 하드코딩 | `config/api_config.json` 도입 (URL, TR ID 등) |
| X-8 | 공통 유틸리티 모듈 없음 | `utils/http_client.py`, `utils/async_utils.py` 추가 |
| X-9 | TypedDict 미사용 — dict 구조가 암묵적 | `from typing import TypedDict` 로 주요 dict 구조 명시화 |

---

## 수정 우선순위

```
즉시 수정 (오케스트레이터 연결 전)
├── EX-1: executor.py raise_for_status 예외 처리
├── EX-2: executor.py _place_order 예외 처리
└── D-1:  data_collector.py 로그 레벨 소문자 통일

다음 스프린트 (모의투자 안정화 기간 중)
├── MA-1/MA-2: market_analyzer.py or 0.0 패턴 교체
├── X-2: asyncio.to_thread() 전환
├── X-3: 메시지 불변성 수정
└── RC-2: recommender.py 정렬 순서 수정

실전 전환 전 (Phase 3 완료 후)
├── EX-7: 주문 수량 weight 기반으로 변경
├── X-6: agent_config.json 도입
└── X-7: api_config.json 도입
```

---

*이 파일은 코드 리뷰 시마다 업데이트합니다.*
*수정 완료 시 해당 행의 `[ ]` → `[x]` 로 변경하세요.*
