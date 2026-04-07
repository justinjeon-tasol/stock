"""
칼만 필터 이동평균선 서비스.

1차원 스칼라 칼만 필터로 주가의 노이즈를 제거하여
적응형 이동평균(Kalman MA)을 산출한다.

전통 MA 대비 장점:
  - 변동성에 맞춰 자동 적응 (고변동 → 둔감, 저변동 → 민감)
  - 추세 전환 감지가 빠르고 휩소(whipsaw)가 적음
  - 파라미터 선택이 기간(일수)이 아닌 노이즈 비율로 직관적
"""

import numpy as np
from typing import Optional


class KalmanMA:
    """1차원 스칼라 칼만 필터."""

    def __init__(
        self,
        process_noise: float = 1e-5,
        measurement_noise: float = 1e-2,
    ):
        self.Q = process_noise       # 프로세스 노이즈 (작을수록 부드러움)
        self.R = measurement_noise   # 관측 노이즈 (클수록 가격 변동 무시)

    def run(self, prices: list) -> list:
        """
        종가 배열을 받아 칼만 MA 배열을 반환한다.

        Args:
            prices: 종가 리스트 (오래된 것 → 최신 순)

        Returns:
            칼만 MA 리스트 (같은 길이)
        """
        if not prices or len(prices) < 2:
            return list(prices)

        n = len(prices)
        x_hat = np.zeros(n)  # 상태 추정값 (칼만 MA)
        P = np.zeros(n)      # 추정 오차 공분산

        # 초기화: 첫 값을 그대로 사용
        x_hat[0] = prices[0]
        P[0] = 1.0

        for k in range(1, n):
            # 예측 단계
            x_pred = x_hat[k - 1]
            P_pred = P[k - 1] + self.Q

            # 갱신 단계
            K = P_pred / (P_pred + self.R)   # 칼만 이득
            x_hat[k] = x_pred + K * (prices[k] - x_pred)
            P[k] = (1 - K) * P_pred

        return x_hat.tolist()


def compute_kalman_signal(
    prices: list,
    current_price: Optional[float] = None,
    process_noise: float = 1e-5,
    measurement_noise: float = 1e-2,
    slope_window: int = 3,
    slope_threshold: float = 0.1,
) -> Optional[dict]:
    """
    종가 배열로부터 칼만 MA 신호를 생성한다.

    Args:
        prices: 종가 리스트 (최소 10개 이상)
        current_price: 실시간 가격 (있으면 마지막 값 대체)
        process_noise: Q 파라미터
        measurement_noise: R 파라미터
        slope_window: 기울기 계산 윈도우 (일)
        slope_threshold: UP/DOWN 판정 기울기 임계값 (%)

    Returns:
        {
            "kalman_ma": float,           최신 칼만 MA
            "trend": "UP" | "DOWN" | "FLAT",
            "price_above_kalman": bool,   현재가 > 칼만 MA
            "crossover": "UP" | "DOWN" | None,   돌파 방향
            "slope_pct": float,           기울기 (%)
            "distance_pct": float,        현재가와 칼만 MA의 거리 (%)
        }
        데이터 부족 시 None 반환.
    """
    if not prices or len(prices) < 10:
        return None

    price_list = list(prices)
    if current_price and current_price > 0:
        price_list[-1] = current_price

    kf = KalmanMA(process_noise=process_noise, measurement_noise=measurement_noise)
    kalman_values = kf.run(price_list)

    if len(kalman_values) < slope_window + 1:
        return None

    latest_price = price_list[-1]
    kalman_ma = kalman_values[-1]
    kalman_ma_prev = kalman_values[-2]

    # 기울기: 최근 N일 칼만 MA 변화율 (%)
    slope_start = kalman_values[-(slope_window + 1)]
    slope_pct = ((kalman_ma - slope_start) / slope_start) * 100 if slope_start != 0 else 0.0

    # 추세 판정
    if slope_pct >= slope_threshold:
        trend = "UP"
    elif slope_pct <= -slope_threshold:
        trend = "DOWN"
    else:
        trend = "FLAT"

    # 현재가 vs 칼만 MA 위치
    price_above = latest_price > kalman_ma

    # 크로스오버 감지: 직전 봉 기준
    prev_price = price_list[-2]
    prev_above = prev_price > kalman_ma_prev

    if not prev_above and price_above:
        crossover = "UP"
    elif prev_above and not price_above:
        crossover = "DOWN"
    else:
        crossover = None

    # 거리 (%)
    distance_pct = ((latest_price - kalman_ma) / kalman_ma) * 100 if kalman_ma != 0 else 0.0

    return {
        "kalman_ma": round(kalman_ma, 2),
        "trend": trend,
        "price_above_kalman": price_above,
        "crossover": crossover,
        "slope_pct": round(slope_pct, 4),
        "distance_pct": round(distance_pct, 4),
    }
