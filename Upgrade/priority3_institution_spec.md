# 우선순위 3: 기관 순매수 하드코딩 0 → 실제 데이터

> **목표**: 외국인만 보는 수급 편향 해소. 외국인+기관 통합 수급 신호 구축.
> **비용**: 0원 (기존 KIS API FHKST01010900이 기관 데이터도 제공)
> **핵심 수정**: data_collector.py에서 항상 0으로 넣는 부분을 실제 값으로 교체

---

## 1. 현재 문제

```python
# data_collector.py:276 또는 733 부근 (실제 라인은 확인 필요)
# 현재 코드에서 기관 순매수를 항상 0으로 하드코딩:

"institution_net": 0,  # ← 항상 0. 실제 데이터 안 넣음

# 반면 외국인 순매수는 실제 KIS API에서 가져옴:
"foreign_net": actual_value,  # ← 실제 데이터
```

### 왜 문제인가?

```
현실: 외국인 매수 + 기관 매수 = 강한 상승 신호
      외국인 매수 + 기관 매도 = 혼재 신호 (불확실)
      외국인 매도 + 기관 매도 = 강한 하락 신호

현재 시스템: 외국인만 보고 판단
      외국인 매수 → "수급 좋다" (1.2x 부스트)
      기관이 동시에 폭매도 중인데도 모름 → 잘못된 판단 가능

수정 후: 외국인 + 기관 통합 판단
      둘 다 매수 → "매우 강한 수급" (1.3x 부스트)
      하나만 매수 → "보통 수급" (1.1x 부스트)
      둘 다 매도 → "수급 악화" (0.6x 감쇠)
```

---

## 2. KIS API 데이터 확인

### 기존 사용 중인 API: FHKST01010900 (주식현재가 투자자)

```python
# data_collector.py:406 부근에서 이미 이 API를 호출하고 있음
# 이 API의 응답에는 외국인 AND 기관 데이터가 모두 포함됨

# KIS API FHKST01010900 응답 예시:
{
    "output": {
        "frgn_ntby_qty": "1523400",    # 외국인 순매수 수량 ← 이미 사용 중
        "orgn_ntby_qty": "892300",     # 기관 순매수 수량 ← 있는데 안 읽음!
        "prsn_ntby_qty": "-2415700",   # 개인 순매수 수량
        # ... 기타 필드
    }
}
```

> **핵심**: 이미 호출하는 API 응답에 기관 데이터가 있다.
> 추가 API 호출 필요 없음. 응답에서 읽기만 하면 된다.

---

## 3. data_collector.py 수정

### 3-1. 기관 순매수 실제 값 추출

```python
# data_collector.py에서 FHKST01010900 응답을 파싱하는 부분을 찾아서 수정

# 기존 코드 (추정):
investor_data = {
    "foreign_net": int(output.get("frgn_ntby_qty", "0")),
    "institution_net": 0,  # ← 이 부분을 수정
}

# 수정 후:
investor_data = {
    "foreign_net": self._safe_int(output.get("frgn_ntby_qty", "0")),
    "institution_net": self._safe_int(output.get("orgn_ntby_qty", "0")),
    # 선택적: 개인 순매수도 추가
    "individual_net": self._safe_int(output.get("prsn_ntby_qty", "0")),
}


def _safe_int(self, value, default=0):
    """KIS API 문자열을 안전하게 int로 변환"""
    try:
        return int(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return default
```

### 3-2. 실제 코드 위치 확인 방법

```
Claude Code에게 다음을 요청:

"data_collector.py에서 'institution_net' 또는 'frgn_ntby_qty'가
있는 모든 위치를 찾아줘. 특히 institution_net이 0으로
하드코딩된 부분과, FHKST01010900 API 응답을 파싱하는 부분."
```

---

## 4. weight_adjuster.py 수정 — 통합 수급 신호

### 4-1. 기존 외국인 부스트 확인

```python
# weight_adjuster.py:735 부근 (실제 라인 확인 필요)
# 기존 _apply_foreign_net_boost() 메서드:

def _apply_foreign_net_boost(self, weight, foreign_net, ...):
    if foreign_net > threshold:
        return weight * 1.2  # 외국인 순매수 → 부스트
    elif foreign_net < -threshold:
        return weight * 0.7  # 외국인 순매도 → 감쇠
    return weight
```

### 4-2. 통합 수급 신호로 확장

```python
def _apply_supply_demand_boost(self, weight, foreign_net, institution_net,
                                volume_ratio=1.0):
    """
    외국인 + 기관 통합 수급 신호로 비중을 조정한다.

    수급 등급:
    - VERY_STRONG: 외국인+기관 동시 순매수 → 1.3x
    - STRONG: 외국인만 순매수 (기관 중립) → 1.2x (기존과 동일)
    - MODERATE: 기관만 순매수 (외국인 중립) → 1.1x
    - NEUTRAL: 혼재 또는 둘 다 중립 → 1.0x
    - WEAK: 외국인만 순매도 → 0.8x
    - VERY_WEAK: 외국인+기관 동시 순매도 → 0.6x

    Parameters:
        weight: 기존 비중
        foreign_net: 외국인 순매수 수량
        institution_net: 기관 순매수 수량
        volume_ratio: 거래량 비율 (참고용)
    """
    # 순매수/매도 판단 임계값
    # (절대 수량 기준 — 종목별 유동주식수 대비 비율이 이상적이나,
    #  초기에는 단순 부호(+/-)로 시작)
    foreign_buying = foreign_net > 0
    foreign_selling = foreign_net < 0
    institution_buying = institution_net > 0
    institution_selling = institution_net < 0

    # 수급 등급 판정
    if foreign_buying and institution_buying:
        # 외국인+기관 동시 매수: 가장 강한 신호
        grade = "VERY_STRONG"
        multiplier = 1.3
    elif foreign_buying and not institution_selling:
        # 외국인 매수, 기관 중립 이상
        grade = "STRONG"
        multiplier = 1.2
    elif institution_buying and not foreign_selling:
        # 기관 매수, 외국인 중립 이상
        grade = "MODERATE"
        multiplier = 1.1
    elif foreign_selling and institution_selling:
        # 외국인+기관 동시 매도: 가장 약한 신호
        grade = "VERY_WEAK"
        multiplier = 0.6
    elif foreign_selling and not institution_buying:
        # 외국인 매도, 기관도 안 사줌
        grade = "WEAK"
        multiplier = 0.8
    elif institution_selling and not foreign_buying:
        # 기관 매도, 외국인도 안 사줌
        grade = "MILD_WEAK"
        multiplier = 0.9
    else:
        # 혼재 (외국인 매수 + 기관 매도 등)
        grade = "MIXED"
        multiplier = 1.0

    adjusted_weight = weight * multiplier

    self.logger.debug(
        f"[수급] 외국인={foreign_net:+,} 기관={institution_net:+,} "
        f"→ {grade} ({multiplier}x)"
    )

    return adjusted_weight, grade
```

### 4-3. 기존 메서드와의 호환

```python
# 기존 _apply_foreign_net_boost()를 호출하는 곳에서
# _apply_supply_demand_boost()로 교체

# 방법 1: 기존 메서드를 래핑 (가장 안전)
def _apply_foreign_net_boost(self, weight, foreign_net, **kwargs):
    """
    기존 인터페이스 유지하면서 기관 데이터도 활용.
    기존 호출 코드를 수정하지 않아도 됨.
    """
    # kwargs에서 institution_net 꺼내기 (없으면 0)
    institution_net = kwargs.get('institution_net', 0)

    if institution_net != 0:
        # 기관 데이터 있으면 통합 신호 사용
        adjusted, grade = self._apply_supply_demand_boost(
            weight, foreign_net, institution_net
        )
        return adjusted
    else:
        # 기관 데이터 없으면 기존 로직 유지
        if foreign_net > 0:
            return weight * 1.2
        elif foreign_net < 0:
            return weight * 0.7
        return weight
```

---

## 5. Filter 3 진입 신호 강화

### 신호 7: 수급 동반 매수 (신규)

```python
# weight_adjuster.py의 check_entry_timing()에 추가

def _check_supply_demand_signal(self, symbol, investor_data):
    """
    외국인+기관 동시 순매수 = 강한 진입 신호.
    '큰 손들이 사고 있는 종목'을 잡는 신호.
    """
    if not investor_data:
        return {
            "name": "수급 동반매수",
            "triggered": False,
            "reason": "투자자 데이터 없음"
        }

    foreign = investor_data.get("foreign_net", 0)
    institution = investor_data.get("institution_net", 0)

    both_buying = foreign > 0 and institution > 0

    # 강도 계산: 둘 다 매수이면서 합산 규모가 클수록 강함
    total_net = foreign + institution

    triggered = both_buying

    return {
        "name": "수급 동반매수",
        "triggered": triggered,
        "weight": 1.2,
        "details": {
            "foreign_net": f"{foreign:+,}",
            "institution_net": f"{institution:+,}",
            "total_net": f"{total_net:+,}",
        },
        "reason": (
            f"외국인({foreign:+,}) + 기관({institution:+,}) 동반 매수"
            if triggered else
            f"동반 매수 아님 (외국인:{foreign:+,}, 기관:{institution:+,})"
        )
    }
```

### 진입 금지 조건 추가

```python
# _check_entry_blockers()에 추가

# --- 차단 9: 외국인+기관 동시 대량 매도 ---
if investor_data:
    foreign = investor_data.get("foreign_net", 0)
    institution = investor_data.get("institution_net", 0)

    if foreign < 0 and institution < 0:
        total_selling = abs(foreign) + abs(institution)
        # 동시 매도 규모가 일정 이상이면 차단
        # (임계값은 종목 유동주식수 대비 비율이 이상적이나,
        #  초기에는 단순 조건으로 시작)
        if total_selling > 0:  # 둘 다 매도
            blockers.append({
                "type": "DUAL_SELLING",
                "reason": (
                    f"외국인({foreign:+,}) + 기관({institution:+,}) "
                    f"동시 순매도 (총 {total_selling:,})"
                ),
                "severity": "MEDIUM"
            })
```

---

## 6. 데이터 흐름

```
기존:
  KIS FHKST01010900 → foreign_net만 추출 → weight_adjuster 부스트
                     → institution_net = 0 (하드코딩, 버림)

수정 후:
  KIS FHKST01010900 → foreign_net 추출 ─────┐
                     → institution_net 추출 ──┤
                     → individual_net 추출 ───┘
                                              ↓
                              통합 수급 등급 판정
                              (VERY_STRONG ~ VERY_WEAK)
                                              ↓
                        ┌─────────────────────────────┐
                        │ weight_adjuster 비중 조정    │
                        │ Filter 3 진입 신호/금지     │
                        │ 예측 보정 (선택적)          │
                        └─────────────────────────────┘
```

---

## 7. Claude Code 실행 프롬프트

```
이 명세서(priority3_institution_spec.md)를 읽고 다음을 실행해줘:

### Step 1: 현재 코드 위치 확인
1. data_collector.py에서 "institution_net"이 0으로 설정되는
   모든 위치를 찾아줘.
2. data_collector.py에서 "FHKST01010900" API를 호출하고
   응답을 파싱하는 부분을 찾아줘.
3. KIS API 응답에서 기관 순매수 필드명이 뭔지 확인해줘.
   (orgn_ntby_qty일 수도 있고 다를 수도 있음)

### Step 2: data_collector.py 수정
4. institution_net = 0 하드코딩을 실제 API 응답값으로 교체.
   필드명은 Step 1에서 확인한 실제 이름 사용.
5. _safe_int() 유틸리티 추가 (이미 있으면 활용).

### Step 3: weight_adjuster.py 수정
6. _apply_supply_demand_boost() 메서드 추가.
7. 기존 _apply_foreign_net_boost() 호출 부분에서
   institution_net도 함께 전달되도록 수정.
   기존 메서드 시그니처는 유지하되, 내부에서
   institution_net 활용하도록.

### Step 4: Filter 3 강화
8. _check_supply_demand_signal() 신호 추가.
9. _check_entry_blockers()에 DUAL_SELLING 차단 추가.

### Step 5: 검증
10. 삼성전자(005930)로 투자자 데이터 조회하여
    foreign_net과 institution_net이 둘 다 실제 값으로
    반환되는지 확인.
11. institution_net이 0이 아닌 값인지 확인.

주의사항:
- 기존 _apply_foreign_net_boost()를 호출하는 모든 곳을 찾아서
  institution_net도 전달되도록 해야 함
- institution_net이 없는 경우 (API 실패 등) 기존대로 0 fallback
- 기존 외국인 부스트 로직이 깨지지 않도록 주의
```
