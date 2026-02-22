"""
제품명(商品名)으로 unit_price.csv에서 유사도 매칭하여 시키리/본부장 단가 조회.
notepad.ipynb의 split_name_and_capacity, find_similar_supers 로직과 동일.
"""
import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Tuple, Optional, List, Dict, Any

import pandas as pd


def split_name_and_capacity(name: str) -> Tuple[str, Optional[str]]:
    """
    "제품명" 등에서 용량(예: １２０Ｇ, 120g, 90ML 등)를 분리해서 (이름, 용량) 튜플로 반환.
    용량이 없으면 (원본, None) 반환.
    단, 단위가 그람(g/ｇ/G/Ｇ)일 때는 숫자만 추출해서 반환.
    """
    pattern = re.compile(
        r"([０-９0-9]+\.?[０-９0-9]*)([gGｇＧmMｍＭlLリットルﾘｯﾄﾙ個コ袋])\s*$"
    )
    to_hankaku = str.maketrans("０１２３４５６７８９", "0123456789")
    name = (name or "").strip()
    m = pattern.search(name)
    if m:
        num = m.group(1).translate(to_hankaku)
        unit = m.group(2)
        if unit in ["g", "G", "ｇ", "Ｇ"]:
            cap = num
        else:
            cap = f"{num}{unit}"
        base = name[: m.start()].strip()
        return base, cap
    return name, None


def _similarity(a: str, b: str) -> float:
    """두 문자열 유사도 0~1 (pg_trgm과 비슷한 개념)."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_similar_products(
    query: str,
    csv_path: Path,
    col: str = "제품명",
    top_k: int = 10,
    min_similarity: float = 0.0,
    sub_col: Optional[str] = "제품용량",
    sub_query: Optional[str] = None,
    sub_min_similarity: float = 0.0,
) -> pd.DataFrame:
    """
    입력한 제품명과 unit_price.csv의 제품명/제품용량 중 유사도 높은 순으로 반환.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"파일 없음: {csv_path}")
    df = pd.read_csv(csv_path, encoding="utf-8")
    if col not in df.columns:
        raise KeyError(f"컬럼 없음: {col}. 사용 가능: {list(df.columns)}")
    if sub_col and sub_col not in df.columns:
        raise KeyError(f"서브 컬럼 없음: {sub_col}. 사용 가능: {list(df.columns)}")

    query = (query or "").strip()
    sub_query = (sub_query or "").strip() if sub_query is not None else None

    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        name = row.get(col) or ""
        if isinstance(name, float) and pd.isna(name):
            name = ""
        name = str(name).strip()
        primary_score = _similarity(query, name)

        if sub_col and sub_query is not None:
            sub_value = row.get(sub_col) or ""
            if isinstance(sub_value, float) and pd.isna(sub_value):
                sub_value = ""
            sub_value = str(sub_value).strip()
            sub_score = _similarity(sub_query, sub_value)
        else:
            sub_score = None

        if primary_score >= min_similarity:
            if sub_col and sub_query is not None:
                if sub_score is not None and sub_score >= sub_min_similarity:
                    row_dict = {
                        **row.to_dict(),
                        f"{col}_similarity": round(primary_score, 4),
                        f"{sub_col}_similarity": round(sub_score, 4),
                    }
                    rows.append(row_dict)
            else:
                row_dict = {**row.to_dict(), "similarity": round(primary_score, 4)}
                rows.append(row_dict)

    if sub_col and sub_query is not None:
        rows.sort(
            key=lambda x: (
                x.get(f"{col}_similarity", 0),
                x.get(f"{sub_col}_similarity", 0),
            ),
            reverse=True,
        )
    else:
        rows.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return pd.DataFrame(rows).head(top_k)
