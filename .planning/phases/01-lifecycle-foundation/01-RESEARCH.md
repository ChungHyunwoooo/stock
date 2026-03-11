# Phase 1: Lifecycle Foundation - Research

**Researched:** 2026-03-11
**Domain:** Strategy state machine, JSON registry management, Discord slash commands
**Confidence:** HIGH

## Summary

Phase 1 implements a finite state machine (FSM) for strategy lifecycle management. The core deliverable is a `LifecycleManager` class that enforces legal state transitions on `strategies/registry.json`, preventing draft strategies from entering live trading. A Discord slash command (`/전략전이`) provides the user-facing interface for state changes with autocomplete and confirmation UX.

The existing codebase already has the foundation: `StrategyStatus` enum (needs `paper` added), `StrategyCatalog` (reads registry.json), Discord bot infrastructure with plugin-based command registration, and the `strategies/{id}/definition.json` + `research.md` convention. The work is primarily **new module creation** (LifecycleManager) and **integration** (Discord command plugin, API router update, StrategyCatalog update).

**Primary recommendation:** Build `LifecycleManager` as a pure domain service in `engine/strategy/lifecycle_manager.py` that owns all registry.json mutations. Wire it into `DiscordBotContext` and the API router. Do NOT touch existing active/deprecated strategies.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- registry.json이 single source of truth -- LifecycleManager가 이 파일만 수정
- deprecated 상태를 archived로 통합 (deprecated_reason -> archived_reason 마이그레이션)
- DB(StrategyRecord)는 전략 상태 관리에서 제외 -- 백테스트 결과/거래 이력 저장소로 한정
- definition.json의 status 필드는 무시 -- registry.json의 status만 사용
- API 전략 조회는 registry.json을 직접 읽어서 응답
- 상태: draft -> testing -> paper -> active -> archived (paper 추가)
- 제한적 역전이 허용: active->paper(강등), testing->draft(되돌리기), archived->draft(재활성화)
- 무작위 역전이 차단 (예: active->draft 불가)
- Phase 1은 상태머신만 구현 -- gate 전제 조건 검증은 Phase 2~3에서 추가
- 전이 이력을 registry.json에 기록: 각 전략 항목에 status_history 배열 [{from, to, date, reason}]
- 단일 커맨드: `/전략전이 [strategy_id] [target_status]`
- Autocomplete 드롭다운으로 등록된 전략 목록 표시 (상태별 필터링)
- 실행 전 확인 버튼 표시 ("전략 X를 paper->active로 승격합니다. 확인/취소")
- 결과는 Discord Embed로 상세 표시: 전략명, 상태변경, 전이이력, 현재 전략 현황 테이블
- research.md 필수 항목: 출처(논문/URL), 전략 로직 요약, 백테스트 결과 요약
- Phase 1에서 레퍼런스 전략 1개만 draft로 등록 (워크플로우 증명 목적)
- 기존 7개 active 전략은 편입하지 않음 -- 신규 등록 전략부터 상태머신 적용

### Claude's Discretion
- 레퍼런스 전략 변환 프로세스(수동/반자동) 설계
- 허용된 전이 맵의 정확한 구현 방식 (dict, 그래프 등)
- Discord Embed 레이아웃 상세
- registry.json 스키마 확장 세부 (status_history 외 필드)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LIFE-01 | 전략 상태가 draft->testing->paper->active->archived 순서로만 전이되며, 규칙 위반 전이를 차단한다 | LifecycleManager FSM 구현, StrategyStatus enum paper 추가, 전이 맵 dict, InvalidTransitionError 예외 |
| LIFE-04 | 논문/커뮤니티의 레퍼런스 전략을 JSON StrategyDefinition으로 변환하는 구조화된 워크플로우가 있다 | 레퍼런스 전략 변환 프로세스 문서화, strategies/{id}/research.md 템플릿, definition.json 생성 체크리스트 |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.6.0 | StrategyDefinition, 스키마 검증 | 프로젝트 전체 스키마 레이어 (engine/schema.py) |
| discord.py | >=2.4.0 | Discord 슬래시 커맨드, Embed, View | 프로젝트 봇 인프라 (app_commands, CommandTree) |
| Python stdlib (json, pathlib, datetime, enum) | 3.11+ | registry.json 읽기/쓰기, FSM | 외부 의존성 불필요 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.0.0 | 전이 규칙 단위 테스트 | LifecycleManager 모든 전이 경로 검증 |
| pytest-asyncio | >=0.23.0 | Discord 커맨드 비동기 테스트 | Discord 커맨드 핸들러 테스트 시 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dict 기반 전이 맵 | python-statemachine 라이브러리 | 상태 5개, 전이 7개로 극소 -- 외부 라이브러리 과잉. dict로 충분 |
| filelock 기반 동시 쓰기 방지 | 없음 (단일 프로세스) | 전략 수 수십 개, 봇 1대 -- 파일 잠금 불필요 |

## Architecture Patterns

### Recommended Project Structure
```
engine/
  strategy/
    lifecycle_manager.py     # LifecycleManager (FSM + registry.json 쓰기)
  interfaces/
    discord/
      commands/
        lifecycle.py         # LifecycleCommandPlugin (/전략전이)
      autocomplete.py        # strategy_autocomplete 추가
      context.py             # DiscordBotContext에 lifecycle_manager 추가
strategies/
  registry.json              # status_history 필드 추가 (신규 전략만)
  {ref_strategy_id}/
    definition.json           # 레퍼런스 전략 정의
    research.md               # 출처, 로직 요약, 백테스트 결과
```

### Pattern 1: Transition Map as Dict
**What:** 허용된 전이를 `dict[StrategyStatus, set[StrategyStatus]]`로 정의
**When to use:** 상태 수가 적고 전이 규칙이 단순할 때
**Example:**
```python
# engine/strategy/lifecycle_manager.py
from engine.schema import StrategyStatus

ALLOWED_TRANSITIONS: dict[StrategyStatus, set[StrategyStatus]] = {
    StrategyStatus.draft: {StrategyStatus.testing},
    StrategyStatus.testing: {StrategyStatus.draft, StrategyStatus.paper},
    StrategyStatus.paper: {StrategyStatus.active},
    StrategyStatus.active: {StrategyStatus.paper, StrategyStatus.archived},
    StrategyStatus.archived: {StrategyStatus.draft},
}
```

### Pattern 2: Discord Command Plugin (기존 패턴 준수)
**What:** `DiscordCommandPlugin` Protocol 구현체로 새 커맨드 등록
**When to use:** 모든 Discord 슬래시 커맨드 추가 시
**Example:**
```python
# engine/interfaces/discord/commands/lifecycle.py
from discord import Interaction, app_commands
from engine.interfaces.discord.commands.base import DiscordCommandPlugin
from engine.interfaces.discord.context import DiscordBotContext

class LifecycleCommandPlugin:
    name = "lifecycle"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="전략전이", description="전략 상태를 변경합니다")
        @app_commands.describe(
            strategy_id="전략 ID",
            target_status="목표 상태 (testing/paper/active/archived/draft)"
        )
        @app_commands.autocomplete(
            strategy_id=strategy_autocomplete,
            target_status=status_autocomplete,
        )
        async def transition(
            interaction: Interaction,
            strategy_id: str,
            target_status: str,
        ) -> None:
            # 확인 버튼 View 표시 후 콜백에서 전이 수행
            ...
```

### Pattern 3: Discord Confirmation View (discord.py ui.View)
**What:** `discord.ui.View` + `discord.ui.Button`으로 확인/취소 인터렉션
**When to use:** 파괴적 동작 전 확인이 필요할 때
**Example:**
```python
import discord

class TransitionConfirmView(discord.ui.View):
    def __init__(self, strategy_id: str, from_status: str, to_status: str, manager):
        super().__init__(timeout=60)
        self.strategy_id = strategy_id
        self.from_status = from_status
        self.to_status = to_status
        self.manager = manager

    @discord.ui.button(label="확인", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = self.manager.transition(self.strategy_id, self.to_status, reason="Discord 커맨드")
        embed = build_transition_embed(result)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="전이가 취소되었습니다.", view=None)
```

### Pattern 4: Registry JSON 원자적 쓰기
**What:** 임시 파일에 쓴 후 rename으로 원자적 교체
**When to use:** registry.json 변경 시 (데이터 손실 방지)
**Example:**
```python
import json
import tempfile
from pathlib import Path

def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
```

### Anti-Patterns to Avoid
- **definition.json의 status를 수정하는 것:** registry.json이 유일한 status source of truth. definition.json의 status 필드는 무시한다.
- **StrategyRepository(DB)에 상태를 저장하는 것:** DB는 백테스트/거래 이력 전용. 상태 관리는 registry.json만.
- **기존 active/deprecated 전략에 상태머신을 적용하는 것:** 신규 전략부터만 적용. 기존 16개 전략은 현행 유지.
- **LifecycleManager 내부에서 Discord/API를 직접 호출하는 것:** 순수 도메인 서비스로 유지. 호출자(Discord, API)가 결과를 가공.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Discord 슬래시 커맨드 등록 | 수동 HTTP 호출 | discord.py app_commands.CommandTree | 프로젝트 기존 패턴, 자동 싱크 |
| Discord UI 확인/취소 | 메시지 리액션 기반 | discord.ui.View + Button | discord.py 2.x 공식 패턴, 타임아웃 내장 |
| Discord autocomplete | 하드코딩 선택지 | app_commands.autocomplete + 동적 조회 | 프로젝트 기존 패턴 (autocomplete.py) |
| JSON 스키마 검증 | 수동 dict 검증 | pydantic BaseModel | 프로젝트 전체 패턴 |

**Key insight:** 상태 5개, 전이 7개의 극소 FSM이므로 python-statemachine 같은 라이브러리는 과잉. dict 1개로 전이 맵을 정의하고 `if target not in ALLOWED[current]: raise` 패턴이면 충분.

## Common Pitfalls

### Pitfall 1: registry.json 동시 쓰기 데이터 손실
**What goes wrong:** 봇이 쓰기 중 크래시하면 JSON이 반쪽짜리로 남음
**Why it happens:** `json.dump` 직접 호출 시 원자성 없음
**How to avoid:** tempfile + rename 패턴 (Pattern 4). 같은 디렉토리에 임시 파일 생성 후 `Path.replace()`로 원자적 교체.
**Warning signs:** 빈 파일, JSON 파싱 에러

### Pitfall 2: StrategyStatus enum에 paper 추가 시 기존 테스트 깨짐
**What goes wrong:** `test_strategy_status_enum`에서 `len(StrategyStatus) == 4` 하드코딩
**Why it happens:** enum 멤버 수를 리터럴로 검증
**How to avoid:** paper 추가 후 해당 테스트를 `len(StrategyStatus) == 5`로 수정. test_schema.py:77 참조.
**Warning signs:** test_schema.py 테스트 실패

### Pitfall 3: 기존 deprecated 전략과 archived 혼용
**What goes wrong:** deprecated_reason 필드가 있는 기존 전략을 archived로 자동 마이그레이션하면 기존 로직 파손
**Why it happens:** CONTEXT.md에서 "deprecated -> archived 통합"이라 했으나, 기존 전략은 건드리지 않기로 결정
**How to avoid:** 신규 전략에만 archived 상태 + archived_reason 적용. 기존 deprecated 항목은 registry.json에서 그대로 유지. LifecycleManager는 `status == "deprecated"`인 항목은 관리 대상에서 제외.
**Warning signs:** 기존 deprecated 전략의 deprecated_reason 필드가 사라지거나 이름이 바뀜

### Pitfall 4: Discord 한글 커맨드 이름 미지원
**What goes wrong:** Discord API가 커맨드 이름에 한글을 거부할 수 있음
**Why it happens:** Discord 공식 문서: 커맨드 이름은 `^[-_\p{L}\p{N}\p{sc=Deva}\p{sc=Thai}]{1,32}$` 패턴. 한글(\p{L}) 포함.
**How to avoid:** discord.py 2.4+에서 `\p{L}`이 한글을 포함하므로 `/전략전이`는 유효. 단, 배포 전 길드 싱크 테스트 필수.
**Warning signs:** `HTTPException: 400 Bad Request` on tree.sync()

### Pitfall 5: StrategyCatalog.list_definitions()에서 active 외 상태 무시
**What goes wrong:** list_definitions()가 `status != "active"`를 필터링하므로, testing/paper 전략이 모니터링에서 누락
**Why it happens:** 현재 코드가 `if entry.get("status") != "active": continue`로 하드코딩
**How to avoid:** Phase 1에서는 StrategyCatalog의 필터 로직을 status 파라미터화하되, 기본값은 active 유지 (하위 호환). 또는 LifecycleManager에서 별도 조회 메서드 제공.
**Warning signs:** paper 전략이 signal 생성 파이프라인에 진입하지 않음 (Phase 2~3 이슈이므로 Phase 1에서는 참고만)

## Code Examples

### LifecycleManager 핵심 구조

```python
# engine/strategy/lifecycle_manager.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.schema import StrategyStatus

class InvalidTransitionError(Exception):
    """허용되지 않는 상태 전이 시도."""

class StrategyNotFoundError(Exception):
    """registry에 존재하지 않는 전략 ID."""

ALLOWED_TRANSITIONS: dict[StrategyStatus, set[StrategyStatus]] = {
    StrategyStatus.draft: {StrategyStatus.testing},
    StrategyStatus.testing: {StrategyStatus.draft, StrategyStatus.paper},
    StrategyStatus.paper: {StrategyStatus.active},
    StrategyStatus.active: {StrategyStatus.paper, StrategyStatus.archived},
    StrategyStatus.archived: {StrategyStatus.draft},
}

class LifecycleManager:
    def __init__(self, registry_path: str | Path = "strategies/registry.json") -> None:
        self.registry_path = Path(registry_path)

    def transition(self, strategy_id: str, target: str, reason: str = "") -> dict:
        """전략 상태를 전이하고 이력을 기록한다. 규칙 위반 시 예외 발생."""
        target_status = StrategyStatus(target)
        registry = self._load()
        entry = self._find_entry(registry, strategy_id)
        current = StrategyStatus(entry["status"])

        if target_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(
                f"{strategy_id}: {current.value} -> {target_status.value} 전이 불가"
            )

        entry["status"] = target_status.value
        history = entry.setdefault("status_history", [])
        history.append({
            "from": current.value,
            "to": target_status.value,
            "date": datetime.now().isoformat(),
            "reason": reason,
        })

        self._save(registry)
        return entry
    ...
```

### registry.json 스키마 확장 (신규 전략 항목)

```json
{
  "id": "ref_rsi_divergence",
  "name": "RSI Divergence",
  "status": "draft",
  "direction": ["LONG", "SHORT"],
  "timeframe": ["1h"],
  "regime": ["ALL"],
  "definition": "strategies/ref_rsi_divergence/definition.json",
  "status_history": [
    {
      "from": null,
      "to": "draft",
      "date": "2026-03-11T10:00:00",
      "reason": "레퍼런스 전략 초기 등록"
    }
  ]
}
```

### Discord Embed 결과 표시

```python
import discord

def build_transition_embed(
    strategy_name: str,
    strategy_id: str,
    from_status: str,
    to_status: str,
    history: list[dict],
) -> discord.Embed:
    color_map = {
        "draft": 0x95A5A6,      # gray
        "testing": 0xF39C12,    # orange
        "paper": 0x3498DB,      # blue
        "active": 0x2ECC71,     # green
        "archived": 0xE74C3C,   # red
    }
    embed = discord.Embed(
        title=f"전략 전이 완료",
        color=color_map.get(to_status, 0x000000),
    )
    embed.add_field(name="전략", value=f"{strategy_name} (`{strategy_id}`)", inline=False)
    embed.add_field(name="상태 변경", value=f"`{from_status}` -> `{to_status}`", inline=True)
    embed.add_field(name="전이 이력", value=f"{len(history)}건", inline=True)
    return embed
```

### 레퍼런스 전략 research.md 템플릿

```markdown
# {전략명} -- Research

## 출처
- **논문/URL**: {링크}
- **저자/커뮤니티**: {출처}

## 전략 로직 요약
- **진입 조건**: {description}
- **청산 조건**: {description}
- **사용 지표**: {indicators}
- **타임프레임**: {timeframes}
- **방향**: {long/short/both}

## 백테스트 결과 요약
| 항목 | 값 |
|------|-----|
| 기간 | {period} |
| 총 수익률 | {return}% |
| 승률 | {win_rate}% |
| Sharpe | {sharpe} |
| 최대 DD | {max_dd}% |

## 메모
{추가 관찰 사항}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| status를 definition.json에 개별 관리 | registry.json 중앙 관리 | Phase 1 (신규) | 상태 일원화, 직접 수정 차단 |
| deprecated 상태 | archived로 통합 (신규 전략) | Phase 1 (신규) | 명칭 표준화 |
| 상태 변경 무제한 | FSM 전이 규칙 강제 | Phase 1 (신규) | draft가 active로 직접 전이 불가 |
| 수동 전략 등록 | 레퍼런스 워크플로우 문서화 | Phase 1 (신규) | 논문->JSON 변환 프로세스 표준화 |

**Deprecated/outdated:**
- `deprecated` 상태명: 신규 전략에서는 `archived`로 대체. 기존 전략의 `deprecated`는 그대로 유지.

## Open Questions

1. **한글 Discord 커맨드 이름 안정성**
   - What we know: Discord API regex `^[-_\p{L}\p{N}...]{1,32}$`에서 `\p{L}`이 한글 포함
   - What's unclear: discord.py 2.4의 내부 validation이 이를 올바르게 통과시키는지 100% 확인 불가 (실 배포 테스트 필요)
   - Recommendation: 구현 후 길드 싱크 테스트. 실패 시 `transition` 같은 영문 이름으로 폴백

2. **기존 deprecated 전략의 장기 처리**
   - What we know: Phase 1에서 기존 전략은 건드리지 않음
   - What's unclear: 향후 deprecated -> archived 마이그레이션 시점/방법
   - Recommendation: Phase 1에서는 무시. 향후 별도 마이그레이션 스크립트로 처리

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.23+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `.venv/bin/python -m pytest tests/test_lifecycle.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFE-01 | 정방향 전이 (draft->testing->paper->active->archived) 성공 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_forward_transitions -x` | Wave 0 |
| LIFE-01 | 허용된 역전이 (active->paper, testing->draft, archived->draft) 성공 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_allowed_reverse_transitions -x` | Wave 0 |
| LIFE-01 | 불허 전이 시 InvalidTransitionError 발생 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_invalid_transitions -x` | Wave 0 |
| LIFE-01 | 전이 이력이 status_history에 기록됨 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_transition_history -x` | Wave 0 |
| LIFE-01 | registry.json 원자적 쓰기 (중간 실패 시 데이터 보존) | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_atomic_write -x` | Wave 0 |
| LIFE-01 | StrategyStatus enum에 paper 포함 (5개 상태) | unit | `.venv/bin/python -m pytest tests/test_schema.py::test_strategy_status_enum -x` | Exists (수정 필요) |
| LIFE-01 | Discord /전략전이 커맨드 등록 및 동작 | integration | `.venv/bin/python -m pytest tests/test_lifecycle_discord.py -x` | Wave 0 |
| LIFE-04 | 레퍼런스 전략 definition.json이 StrategyDefinition으로 파싱됨 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_reference_strategy_valid -x` | Wave 0 |
| LIFE-04 | 레퍼런스 전략이 registry.json에 draft로 등록됨 | unit | `.venv/bin/python -m pytest tests/test_lifecycle.py::test_register_strategy -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_lifecycle.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_lifecycle.py` -- LifecycleManager 전이 규칙 + registry.json 조작 테스트
- [ ] `tests/test_lifecycle_discord.py` -- Discord 커맨드 플러그인 테스트 (mock interaction)
- [ ] `tests/test_schema.py::test_strategy_status_enum` -- paper 추가 반영 (기존 파일 수정)

## Sources

### Primary (HIGH confidence)
- Codebase analysis: engine/schema.py (StrategyStatus enum, StrategyDefinition model)
- Codebase analysis: strategies/registry.json (현재 16개 전략 구조)
- Codebase analysis: engine/interfaces/discord/ (봇 인프라, 커맨드 플러그인 패턴)
- Codebase analysis: engine/application/trading/strategies.py (StrategyCatalog)
- Codebase analysis: api/routers/strategies.py (API 상태 업데이트 엔드포인트)
- pyproject.toml: discord.py>=2.4.0, pydantic>=2.6.0, pytest>=8.0.0

### Secondary (MEDIUM confidence)
- Discord API docs: slash command naming regex (한글 지원 여부)
- discord.py 2.x docs: ui.View, ui.Button, Embed API

### Tertiary (LOW confidence)
- Discord 한글 커맨드 이름 실 동작 여부 -- 배포 테스트 전까지 확인 불가

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 프로젝트 기존 의존성 그대로 사용, 신규 라이브러리 없음
- Architecture: HIGH - 기존 패턴(Plugin Protocol, Port/Adapter) 100% 준수
- Pitfalls: HIGH - 코드베이스 직접 분석으로 모든 충돌 지점 식별 완료

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (안정적 도메인, 외부 의존성 변경 없음)
