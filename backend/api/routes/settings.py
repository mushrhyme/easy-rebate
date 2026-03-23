"""
설정 API — 사용자 UI 설정(검토 그리드 컬럼 순서 등)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from database.registry import get_db
from backend.core.auth import get_current_user

router = APIRouter()


class ReviewGridColumnOrderResponse(BaseModel):
    """GET 응답 — column_keys: 저장된 비동결 컬럼 키 순서, 없으면 null"""

    column_keys: Optional[List[str]] = None


class ReviewGridColumnOrderBody(BaseModel):
    """PUT 요청 본문 — 예: { \"column_keys\": [\"得意先\", \"金額\"] }"""

    column_keys: List[str] = Field(default_factory=list)

    @field_validator("column_keys")
    @classmethod
    def validate_keys(cls, v: List[str]) -> List[str]:
        if len(v) > 400:
            raise ValueError("too many column keys")
        for k in v:
            if not isinstance(k, str) or len(k) > 240:
                raise ValueError("invalid column key")
        return v


@router.get("/review-grid-column-order", response_model=ReviewGridColumnOrderResponse)
async def get_review_grid_column_order(
    user_info: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = user_info["user_id"]
    keys = await db.run_sync(db.get_review_grid_column_order, user_id)
    return ReviewGridColumnOrderResponse(column_keys=keys)


@router.put("/review-grid-column-order", response_model=ReviewGridColumnOrderResponse)
async def put_review_grid_column_order(
    body: ReviewGridColumnOrderBody,
    user_info: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = user_info["user_id"]
    ok = await db.run_sync(db.set_review_grid_column_order, user_id, body.column_keys)
    if not ok:
        raise HTTPException(status_code=500, detail="failed to save column order")
    return ReviewGridColumnOrderResponse(column_keys=body.column_keys)
