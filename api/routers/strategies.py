
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import logging

from api.dependencies import get_db
from engine.schema import StrategyDefinition
from engine.core.db_models import StrategyRecord
from engine.core.repository import StrategyRepository
from engine.strategy.lifecycle_manager import (
    InvalidTransitionError,
    LifecycleManager,
    StrategyNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])
_repo = StrategyRepository()
_lifecycle = LifecycleManager()

class StrategyResponse(BaseModel):
    id: int
    name: str
    version: str
    status: str
    definition_json: str
    created_at: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_record(cls, r: StrategyRecord) -> StrategyResponse:
        return cls(
            id=r.id,
            name=r.name,
            version=r.version,
            status=r.status,
            definition_json=r.definition_json,
            created_at=str(r.created_at)[:19] if r.created_at else None,
            updated_at=str(r.updated_at)[:19] if r.updated_at else None,
        )

class StatusUpdate(BaseModel):
    status: str

@router.get("", response_model=list[StrategyResponse])
def list_strategies(
    status: str | None = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> list[StrategyResponse]:
    records = _repo.list_all(db, status=status)
    return [StrategyResponse.from_record(r) for r in records]

@router.post("", response_model=StrategyResponse, status_code=201)
def create_strategy(
    body: StrategyDefinition,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> StrategyResponse:
    record = _repo.save(db, body)
    return StrategyResponse.from_record(record)

@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> StrategyResponse:
    record = _repo.get(db, strategy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyResponse.from_record(record)

@router.patch("/{strategy_id}/status", response_model=StrategyResponse)
def update_status(
    strategy_id: int,
    body: StatusUpdate,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> StrategyResponse:
    record = _repo.get(db, strategy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # If strategy exists in registry.json, validate transition via LifecycleManager
    try:
        _lifecycle.get_strategy(record.name)
        # Strategy found in registry -- enforce FSM rules
        try:
            _lifecycle.transition(record.name, body.status, reason="API PATCH")
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    except StrategyNotFoundError:
        # Not in registry.json -- use existing DB-only logic (no FSM validation)
        pass

    _repo.update_status(db, strategy_id, body.status)
    record = _repo.get(db, strategy_id)
    return StrategyResponse.from_record(record)  # type: ignore[arg-type]

@router.delete("/{strategy_id}", status_code=204)
def delete_strategy(
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> None:
    record = _repo.get(db, strategy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    _repo.delete(db, strategy_id)
