"""
코드 버전 조회 서비스.

trades/positions 레코드에 "어느 버전 코드가 낸 매매인지" 기록하기 위해 사용.
git describe --tags 기반으로 버전 문자열을 얻고, 프로세스 수명 동안 캐시한다.

버전 결정 우선순위:
  1. 환경 변수 CODE_VERSION (배포 스크립트에서 명시적으로 지정 가능)
  2. `git describe --tags --always --dirty` 결과
  3. "unknown" (git 미설치/저장소 아님 등)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_cached_version: str | None = None


def _run_git_describe() -> str | None:
    """git describe 실행. 실패 시 None."""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out or None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug(f"[version] git describe 실패: {e}")
    return None


def get_version() -> str:
    """현재 실행 중인 코드 버전 문자열 반환. 최초 1회만 git 호출, 이후 캐시."""
    global _cached_version
    if _cached_version is not None:
        return _cached_version

    env_version = os.getenv("CODE_VERSION", "").strip()
    if env_version:
        _cached_version = env_version
        return _cached_version

    git_version = _run_git_describe()
    _cached_version = git_version or "unknown"
    return _cached_version


def reset_cache() -> None:
    """테스트용: 캐시 리셋."""
    global _cached_version
    _cached_version = None
