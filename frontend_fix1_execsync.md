# 프론트엔드 병목 1: execSync → Supabase 직접 조회

> **목표**: API 라우트에서 Python을 동기 실행하는 2~5초 블로킹 제거
> **원칙**: 백엔드가 이미 Supabase에 저장하는 데이터를 프론트엔드가 직접 읽도록 변경
> **영향 범위**: `app/api/account-balance/route.ts`, `app/api/prices/route.ts`

---

## 1. 현재 문제

```
유저가 대시보드 열기
  ↓
Next.js API 라우트 호출
  ↓
execSync("python scripts/get_balance.py")  ← 2~5초 블로킹
  ↓                                           Python 프로세스 생성
  ↓                                           KIS API 호출
  ↓                                           응답 파싱
  ↓                                           stdout으로 출력
  ↓
JSON 파싱 → 프론트에 반환
  ↓
화면 렌더링

문제:
1. Python 프로세스 생성 오버헤드: ~500ms
2. KIS API 네트워크 왕복: ~1~3초
3. execSync = 동기 → Next.js 서버 전체 블로킹
4. 다른 유저/요청도 이 시간 동안 응답 불가
```

### 해결 방향

```
수정 후:

유저가 대시보드 열기
  ↓
Next.js API 라우트 호출 (또는 클라이언트에서 직접)
  ↓
Supabase에서 직접 조회 ← 50~200ms
  ↓
화면 렌더링

이유: 백엔드(orchestrator)가 이미 account_summary, positions,
market_phases 등을 Supabase에 저장하고 있음.
Python을 다시 실행할 이유가 없음.
```

---

## 2. 수정 대상 분석

### 2-1. `/api/account-balance/route.ts`

```
Claude Code에서 먼저 확인할 것:
이 파일의 전체 코드를 보여줘. 특히:
- execSync로 어떤 Python 스크립트를 실행하는지
- 그 스크립트가 KIS API의 어떤 데이터를 가져오는지
- 반환하는 JSON 구조가 뭔지
```

**예상 구조:**
```typescript
// 현재 (추정)
import { execSync } from 'child_process';

export async function GET() {
  const result = execSync('python scripts/get_balance.py', {
    encoding: 'utf-8',
    timeout: 30000,
  });
  const data = JSON.parse(result);
  return Response.json(data);
}
```

**수정 방향:**
```typescript
// 수정 후: Supabase에서 직접 조회
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export async function GET() {
  // account_summary 테이블에서 최신 데이터 조회
  const { data, error } = await supabase
    .from('account_summary')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(1)
    .single();

  if (error) {
    return Response.json(
      { error: 'Failed to fetch account balance' },
      { status: 500 }
    );
  }

  // 기존 Python 스크립트가 반환하던 형식에 맞게 매핑
  // (실제 필드명은 기존 코드 확인 후 조정)
  return Response.json({
    total_balance: data.total_balance,
    available_cash: data.available_cash,
    invested_amount: data.invested_amount,
    profit_loss: data.profit_loss,
    profit_loss_pct: data.profit_loss_pct,
    updated_at: data.created_at,
  });
}
```

### 2-2. `/api/prices/route.ts`

```
Claude Code에서 먼저 확인할 것:
이 파일의 전체 코드를 보여줘. 특히:
- 어떤 종목의 가격을 조회하는지
- 실시간 가격인지, 일봉 데이터인지
- 반환하는 JSON 구조가 뭔지
```

**수정 방향 — 경우에 따라 다름:**

```typescript
// Case A: 보유 종목 현재가 조회인 경우
// → positions 테이블에 이미 current_price가 있을 가능성 높음

export async function GET() {
  const { data, error } = await supabase
    .from('positions')
    .select('symbol, current_price, avg_price, quantity, profit_pct, updated_at')
    .eq('is_active', true);

  if (error) {
    return Response.json({ error: 'Failed to fetch prices' }, { status: 500 });
  }

  return Response.json(data);
}

// Case B: 특정 종목 실시간 시세 조회인 경우
// → KIS API 직접 호출로 교체 (Python 경유 불필요)
// → 또는 market_snapshots 테이블에서 최근 데이터 조회

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get('symbol');

  const { data, error } = await supabase
    .from('market_snapshots')
    .select('*')
    .eq('symbol', symbol)
    .order('created_at', { ascending: false })
    .limit(1)
    .single();

  return Response.json(data);
}
```

---

## 3. 나머지 API 라우트 점검

### execSync 사용 여부 확인

```
Claude Code에서 확인:
"frontend/app/api/ 디렉토리의 모든 route.ts 파일에서
execSync, exec, spawn, child_process를 사용하는 곳을 전부 찾아줘"
```

| API 라우트 | execSync 사용 | 수정 방향 |
|------------|:---:|-----------|
| `/api/account-balance` | YES | → Supabase `account_summary` 직접 조회 |
| `/api/prices` | YES | → Supabase `positions` 또는 `market_snapshots` 조회 |
| `/api/account-history` | 확인 필요 | → Supabase `account_history` 직접 조회 |
| `/api/config` | 확인 필요 | → 설정 파일 직접 읽기 또는 Supabase |
| `/api/strategy-report` | 확인 필요 | → Supabase `strategies` 직접 조회 |

---

## 4. 데이터 신선도 보장

### "DB 데이터가 오래된 거면 어쩌나?"

```
걱정 없음. orchestrator가 이미 주기적으로 업데이트하고 있음:

- account_summary: 매 사이클(30분)마다 갱신
- positions: 매 사이클 + 매매 시 즉시 갱신
- market_phases: 매 사이클마다 갱신
- market_snapshots: 모니터링 루프(1~3분)마다 갱신

프론트엔드가 보여줄 데이터의 "최신" = 최근 1~30분 이내
트레이딩 대시보드에서 이 정도면 충분 (초단위 실시간은 불필요)
```

### 데이터 갱신 시점 표시 (선택적)

```typescript
// 컴포넌트에서 "마지막 업데이트" 시간 표시
<span className="text-xs text-gray-400">
  최종 갱신: {formatDistanceToNow(data.updated_at, { locale: ko })}
</span>
```

---

## 5. 프론트엔드에서 API 라우트 제거 가능성

### 더 나은 접근: API 라우트 자체를 없애기

```
현재:
  클라이언트 → Next.js API 라우트 → (execSync Python) → KIS API → 응답
  약 3~5초

API 라우트 유지 (execSync만 제거):
  클라이언트 → Next.js API 라우트 → Supabase → 응답
  약 200~500ms

API 라우트 제거 (클라이언트 직접 조회):
  클라이언트 → Supabase → 응답
  약 100~300ms (가장 빠름)
```

**클라이언트에서 Supabase 직접 조회가 가능한 이유:**
- 이미 `@supabase/supabase-js`가 프론트엔드에 설치됨
- 이미 다른 컴포넌트(usePositions, useAccountSummary 등)에서 직접 조회 중
- RLS(Row Level Security)로 보안 처리 가능

```typescript
// 이미 이런 패턴이 프론트엔드 코드에 존재:
// hooks/useAccountSummary.ts
const { data } = await supabase
  .from('account_summary')
  .select('*')
  .order('created_at', { ascending: false })
  .limit(1);
```

**즉, API 라우트를 통해 Python을 실행하는 것은
이미 프론트엔드가 직접 하고 있는 일의 불필요한 우회임.**

---

## 6. API 라우트별 수정 또는 제거 판단

| API 라우트 | 역할 | Supabase 대체 가능? | 권장 |
|---|---|---|---|
| `/api/account-balance` | 계좌 잔고 조회 | `account_summary` 테이블 | **제거** — useAccountSummary 훅이 이미 동일 역할 |
| `/api/prices` | 종목 가격 조회 | `positions` 테이블 | **제거** — usePositions 훅이 이미 동일 역할 |
| `/api/account-history` | 계좌 이력 | `account_history` 테이블 | **제거 또는 Supabase 교체** |
| `/api/config` | 설정 조회 | 설정 파일 직접 | **유지** (서버 파일 읽기는 API 라우트 필요) |
| `/api/strategy-report` | 전략 리포트 | `strategies` 테이블 | **Supabase 교체** |

---

## 7. Claude Code 실행 프롬프트

```
이 명세서(frontend_fix1_execsync.md)를 읽고 다음을 실행해줘:

### Step 1: 현재 상태 확인
1. frontend/app/api/ 디렉토리의 모든 route.ts 파일 내용을 보여줘.
2. 각 파일에서 execSync, exec, spawn, child_process 사용 부분을 찾아줘.
3. 각 파일이 반환하는 JSON 구조(필드명)를 확인해줘.

### Step 2: 대체 데이터 소스 매핑
4. 각 API 라우트가 Python으로 가져오는 데이터가
   Supabase의 어떤 테이블에 이미 있는지 매핑해줘.
5. 해당 Supabase 테이블을 직접 조회하는
   프론트엔드 훅(hooks/)이 이미 있는지 확인해줘.

### Step 3: execSync 제거
6. 이미 프론트엔드 훅이 동일 역할을 하는 API 라우트는 삭제하고,
   해당 API를 호출하는 컴포넌트가 있다면
   기존 Supabase 훅을 사용하도록 교체.

7. 프론트엔드 훅이 없는 API 라우트는
   execSync를 Supabase 직접 조회로 교체.

8. /api/config처럼 서버 파일 읽기가 필요한 라우트는
   execSync가 아닌 fs.readFile (비동기)로 교체.

### Step 4: 검증
9. 모든 API 라우트에서 child_process import가
   완전히 제거되었는지 확인.
10. 대시보드 페이지가 정상 렌더링되는지 확인.
11. 삭제한 API 라우트를 호출하는 코드가 남아있지 않은지 확인.

### 주의사항
- 기존 API 라우트가 반환하던 JSON 필드명을 유지해야 함
  (프론트엔드 컴포넌트가 그 필드명을 참조하고 있을 수 있음)
- API 라우트 삭제 시, 해당 API를 fetch()로 호출하는
  모든 컴포넌트를 찾아서 Supabase 훅으로 교체
- /api/config는 삭제하지 말고 비동기로만 변경
```
