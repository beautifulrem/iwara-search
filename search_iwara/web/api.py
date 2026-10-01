"""JSON endpoints used by the filter autocomplete."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ..models import ENTITY_KINDS
from .context import SearchDep
from .query import AutocompleteParams

router = APIRouter(prefix="/api", tags=["api"])


class EntityOut(BaseModel):
    id: int
    name: str


@router.get("/{kind}", name="autocomplete", response_model=list[EntityOut])
def autocomplete(
    kind: str,
    params: Annotated[AutocompleteParams, Query()],
    search: SearchDep,
    response: Response,
) -> list[EntityOut]:
    if kind not in ENTITY_KINDS:
        raise HTTPException(status_code=404, detail="unknown entity kind")
    response.headers["Cache-Control"] = "public, max-age=60"
    return [
        EntityOut(id=item.id, name=item.name)
        for item in search.autocomplete(kind, params.query, limit=params.limit)
    ]
