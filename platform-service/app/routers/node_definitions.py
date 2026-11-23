from __future__ import annotations

from fastapi import APIRouter

from app.database import session_scope
from app.serialization import ok
from app.services import node_definitions

router = APIRouter(prefix="/api/node-definitions", tags=["nodes"])


@router.get("")
def list_nodes():
    with session_scope() as session:
        return ok(node_definitions.list_definitions(session))
