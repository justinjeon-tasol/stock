"""
시스템 진입점.
argparse로 실행 모드를 선택한다.

사용법:
  python main.py                        # 기본: 1회 실행
  python main.py --mode once            # 1회 실행
  python main.py --mode schedule        # 30분 주기 반복
  python main.py --mode schedule --interval 60  # 60분 주기 반복
  python main.py --mode update-history  # 히스토리 데이터 최신화 (최근 30일)
  python main.py --mode fetch-history   # 히스토리 데이터 전체 재수집 (5년)
"""

import argparse
import asyncio
import io
import logging
import sys

from orchestrator import Orchestrator


def setup_logging(level: str = "INFO") -> None:
    """루트 로거 설정."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    # Windows 콘솔은 기본 CP949 → 한글 깨짐 방지
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def main():
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="한국 주식 추천 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python main.py                         # 1회 실행\n"
            "  python main.py --mode schedule         # 30분 주기 반복\n"
            "  python main.py --mode schedule --interval 60  # 60분 주기\n"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["once", "schedule", "update-history", "fetch-history", "long-check", "long-register"],
        default="once",
        help="실행 모드: once(1회) | schedule(반복) | update-history | fetch-history | long-check(장기 종목 체크) | long-register(장기 종목 등록)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="schedule 모드 반복 주기 (분 단위, 기본값: 30)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본값: INFO)",
    )
    args = parser.parse_args()

    # 로거 설정
    setup_logging(args.log_level)

    if args.mode in ("update-history", "fetch-history"):
        _run_history_update(args.mode)
        return

    if args.mode == "long-check":
        _run_long_term_check()
        return

    if args.mode == "long-register":
        _run_long_term_register()
        return

    # 오케스트레이터 생성 및 실행
    orchestrator = Orchestrator()

    if args.mode == "once":
        asyncio.run(orchestrator.run_once())
    else:
        asyncio.run(orchestrator.run_scheduled(args.interval))


def _run_long_term_check() -> None:
    """
    장기 포트폴리오 종목 체크 (1일 1회, 장 마감 후 실행 권장).

    - 장기 종목의 SL/트레일링 스탑 체크
    - 고점 갱신 시 SL 상향
    - 대폭락장 전환 시 경고
    """
    import logging
    from database.db import get_open_positions, save_exit_plan, get_exit_plan
    from agents.horizon_manager import HorizonManager
    from agents.position_manager import PositionManager

    logger = logging.getLogger("long_term")
    logger.info("[장기] 장기 포트폴리오 체크 시작")

    positions = get_open_positions(portfolio_type="long")
    if not positions:
        logger.info("[장기] 장기 보유 종목 없음")
        return

    pm = PositionManager()
    hm = HorizonManager()

    for pos in positions:
        code = pos.get("code", "")
        name = pos.get("name", "")
        avg_price = float(pos.get("avg_price", 0))
        quantity = int(pos.get("quantity", 0))
        position_id = pos.get("id", "")

        if avg_price <= 0:
            continue

        # 현재가 조회 (동기)
        current_price = pm._fetch_price_yfinance(code)
        if not current_price or float(current_price) <= 0:
            logger.warning(f"[장기] {name}({code}) 현재가 조회 실패")
            continue
        current_price = float(current_price)

        pnl_pct = (current_price / avg_price - 1) * 100
        logger.info(f"[장기] {name}({code}) 현재가={current_price:,.0f} 손익={pnl_pct:+.2f}%")

        # exit_plan 확인/생성
        plan = get_exit_plan(position_id)
        if not plan:
            # 장기 전용 exit_plan 생성
            tp_pct, sl_pct = hm.get_tp_sl("장기")
            h_cfg = hm.get_horizon_params("장기")
            sl_price = round(avg_price * (1 + sl_pct / 100))
            plan = {
                "position_id": position_id,
                "code": code, "name": name,
                "avg_price": avg_price, "quantity": quantity,
                "holding_period": "장기",
                "plan_type": "FIXED_AT_BUY",
                "exit_stages": [
                    {"stage": 1, "type": "PARTIAL_TP",
                     "trigger_price": round(avg_price * 1.20),
                     "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
                     "status": "PENDING", "rationale": "1차 익절 (매입+20%)"},
                    {"stage": 2, "type": "PARTIAL_TP",
                     "trigger_price": round(avg_price * 1.40),
                     "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
                     "status": "PENDING", "rationale": "2차 익절 (매입+40%)"},
                    {"stage": 3, "type": "FINAL_TP",
                     "trigger_price": round(avg_price * 1.60),
                     "sell_ratio": 1.0,
                     "sell_qty": max(1, quantity - max(1, int(quantity * 0.3)) * 2),
                     "status": "PENDING", "rationale": "잔량 청산 (매입+60%)"},
                ],
                "dynamic_sl": {
                    "initial_sl_price": sl_price,
                    "current_sl_price": sl_price,
                    "sl_pct": sl_pct,
                    "trailing_enabled": True,
                    "trailing_activate_pct": float(h_cfg.get("trailing_activate_pct", 8.0)),
                    "trailing_drop_pct": float(h_cfg.get("trailing_stop_pct", 4.0)),
                    "peak_price": avg_price,
                },
                "plan_version": 1,
            }
            save_exit_plan(plan)
            logger.info(f"[장기] {name}({code}) exit_plan 생성: SL={sl_price:,.0f}")

        # 트레일링 스탑 체크 (상향만)
        dsl = plan.get("dynamic_sl", {})
        old_peak = float(dsl.get("peak_price", 0))
        old_sl = float(dsl.get("current_sl_price", 0))

        if current_price > old_peak:
            dsl["peak_price"] = current_price
            activate_pct = float(dsl.get("trailing_activate_pct", 8.0))
            drop_pct = float(dsl.get("trailing_drop_pct", 4.0))
            gain_pct = (current_price / avg_price - 1) * 100
            if gain_pct >= activate_pct and drop_pct > 0:
                new_sl = round(current_price * (1 - drop_pct / 100))
                if new_sl > old_sl:
                    dsl["current_sl_price"] = new_sl
                    logger.info(
                        f"[장기] {name}({code}) 트레일링 SL 상향: "
                        f"{old_sl:,.0f} → {new_sl:,.0f} (고점 {current_price:,.0f})")
            plan["dynamic_sl"] = dsl
            save_exit_plan(plan)

        # 손절 체크
        current_sl = float(dsl.get("current_sl_price", 0))
        if current_sl > 0 and current_price <= current_sl:
            logger.warning(
                f"[장기] {name}({code}) 손절 도달! "
                f"현재가 {current_price:,.0f} <= SL {current_sl:,.0f} "
                f"(pnl={pnl_pct:+.2f}%) — 수동 매도 검토 필요")

        # 익절 단계 체크
        for stage in plan.get("exit_stages", []):
            if stage.get("status") != "PENDING":
                continue
            trigger = float(stage.get("trigger_price", 0))
            if trigger > 0 and current_price >= trigger:
                logger.warning(
                    f"[장기] {name}({code}) 익절 조건 충족! "
                    f"stage {stage.get('stage')}: 현재가 {current_price:,.0f} >= {trigger:,.0f} "
                    f"— 수동 매도 검토 필요")

    logger.info("[장기] 장기 포트폴리오 체크 완료")


def _run_long_term_register() -> None:
    """
    장기 종목 수동 등록.
    사용법: python main.py --mode long-register
    대화형으로 종목코드, 종목명, 수량, 매입가를 입력받는다.
    """
    from database.db import save_position, save_exit_plan
    from agents.horizon_manager import HorizonManager

    print("=== 장기 종목 등록 ===")
    code = input("종목코드 (예: 005930): ").strip()
    name = input("종목명 (예: 삼성전자): ").strip()
    quantity = int(input("수량: ").strip())
    avg_price = float(input("매입단가: ").strip())

    if not code or not name or quantity <= 0 or avg_price <= 0:
        print("입력값이 올바르지 않습니다.")
        return

    position_id = save_position(
        code=code, name=name, avg_price=avg_price,
        buy_order_id="MANUAL_LONG",
        quantity=quantity, phase="",
        mode="REAL", holding_period="장기",
        portfolio_type="long",
    )

    if not position_id:
        print(f"포지션 저장 실패 (이미 OPEN 포지션이 있을 수 있음)")
        return

    # 장기 전용 exit_plan 자동 생성
    hm = HorizonManager()
    tp_pct, sl_pct = hm.get_tp_sl("장기")
    h_cfg = hm.get_horizon_params("장기")
    sl_price = round(avg_price * (1 + sl_pct / 100))

    plan = {
        "position_id": position_id,
        "code": code, "name": name,
        "avg_price": avg_price, "quantity": quantity,
        "holding_period": "장기",
        "plan_type": "FIXED_AT_BUY",
        "exit_stages": [
            {"stage": 1, "type": "PARTIAL_TP",
             "trigger_price": round(avg_price * 1.20),
             "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
             "status": "PENDING", "rationale": "1차 익절 (매입+20%)"},
            {"stage": 2, "type": "PARTIAL_TP",
             "trigger_price": round(avg_price * 1.40),
             "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
             "status": "PENDING", "rationale": "2차 익절 (매입+40%)"},
            {"stage": 3, "type": "FINAL_TP",
             "trigger_price": round(avg_price * 1.60),
             "sell_ratio": 1.0,
             "sell_qty": max(1, quantity - max(1, int(quantity * 0.3)) * 2),
             "status": "PENDING", "rationale": "잔량 청산 (매입+60%)"},
        ],
        "dynamic_sl": {
            "initial_sl_price": sl_price,
            "current_sl_price": sl_price,
            "sl_pct": sl_pct,
            "trailing_enabled": True,
            "trailing_activate_pct": float(h_cfg.get("trailing_activate_pct", 8.0)),
            "trailing_drop_pct": float(h_cfg.get("trailing_stop_pct", 4.0)),
            "peak_price": avg_price,
        },
        "plan_version": 1,
    }
    save_exit_plan(plan)

    print(f"\n등록 완료!")
    print(f"  종목: {name}({code}) {quantity}주 @ {avg_price:,.0f}원")
    print(f"  포트폴리오: 장기")
    print(f"  SL: {sl_price:,.0f}원 ({sl_pct}%)")
    print(f"  TP1: {avg_price * 1.20:,.0f}원 (+20%)")
    print(f"  TP2: {avg_price * 1.40:,.0f}원 (+40%)")
    print(f"  TP3: {avg_price * 1.60:,.0f}원 (+60%)")
    print(f"  트레일링: +{h_cfg.get('trailing_activate_pct', 8)}%에서 활성 → 고점 -{h_cfg.get('trailing_stop_pct', 4)}% 청산")


def _run_history_update(mode: str) -> None:
    """히스토리 데이터 수집 (fetch_history.py 래퍼)."""
    import subprocess
    import os
    script = os.path.join(os.path.dirname(__file__), "data", "history", "fetch_history.py")
    if mode == "update-history":
        cmd = [sys.executable, script, "--update"]
    else:
        cmd = [sys.executable, script]
    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    main()
