from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NodeDefinition


def list_definitions(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(NodeDefinition)
        .where(NodeDefinition.enabled == 1)
        .order_by(NodeDefinition.sort.asc(), NodeDefinition.id.asc())
    ).all()
    result = []
    for item in rows:
        try:
            schema = json.loads(item.config_schema) if item.config_schema else []
        except ValueError:
            schema = []
        result.append(
            {
                "type": item.type,
                "name": item.name,
                "category": item.category,
                "icon": item.icon,
                "color": item.color,
                "description": item.description,
                "configSchema": schema,
                "sort": item.sort,
            }
        )
    return result
