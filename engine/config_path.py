"""프로젝트 경로 중앙 관리.

config/ — 설정 (변경 빈도 낮음)
state/  — 런타임 상태 (자동 생성, 변경 빈도 높음)
"""

from pathlib import Path

# 프로젝트 루트 (engine/ 의 상위)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

def config_dir() -> Path:
    """config/ 디렉토리 경로 반환."""
    return _PROJECT_ROOT / "config"

def config_file(name: str) -> Path:
    """config/{name} 파일 경로 반환."""
    return _PROJECT_ROOT / "config" / name

def state_dir() -> Path:
    """state/ 디렉토리 경로 반환."""
    d = _PROJECT_ROOT / "state"
    d.mkdir(exist_ok=True)
    return d

def state_file(name: str) -> Path:
    """state/{name} 파일 경로 반환."""
    d = _PROJECT_ROOT / "state"
    d.mkdir(exist_ok=True)
    return d / name
