"""프로젝트 config 디렉토리 경로 중앙 관리.

모든 모듈은 이 함수를 통해 config 파일 경로를 얻는다.
하드코딩된 Path(__file__).resolve().parent... 반복 제거.
"""
from __future__ import annotations

from pathlib import Path

# 프로젝트 루트 (engine/ 의 상위)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """config/ 디렉토리 경로 반환."""
    return _PROJECT_ROOT / "config"


def config_file(name: str) -> Path:
    """config/{name} 파일 경로 반환."""
    return _PROJECT_ROOT / "config" / name
