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
        choices=["once", "schedule", "update-history", "fetch-history"],
        default="once",
        help="실행 모드: once(1회) | schedule(반복) | update-history(히스토리 최신화) | fetch-history(전체 재수집)",
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

    # 오케스트레이터 생성 및 실행
    orchestrator = Orchestrator()

    if args.mode == "once":
        asyncio.run(orchestrator.run_once())
    else:
        asyncio.run(orchestrator.run_scheduled(args.interval))


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
