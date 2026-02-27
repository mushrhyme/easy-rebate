"""
제품명(商品名)으로 unit_price.csv에서 유사도 매칭하여 시키리/본부장 단가 조회.
- 제품명/용량 유사도: 여기서는 difflib 사용 (notepad.ipynb의 split_name_and_capacity, 유사도 로직과 동일).
- 슈퍼명 유사도(담당 필터 등): DB에서 pg_trgm similarity() 사용 (db_manager).
"""
import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Tuple, Optional, List, Dict, Any  # Tuple for resolve_product_and_prices

import pandas as pd


def split_name_and_capacity(name: str) -> Tuple[str, Optional[str]]:
    """
    "제품명" 등에서 용량을 분리해서 (이름, 용량) 튜플로 반환.
    - １２０ｇ×３ → 120*3=360, 용량 "360" (g는 숫자만)
    - １２０Ｇ, 120g, 90ML 등 단일 → 기존과 동일
    용량이 없으면 (원본, None) 반환.
    """
    to_hankaku = str.maketrans("０１２３４５６７８９", "0123456789")
    name = (name or "").strip()
    # 패턴1: 数字+単位×数字 (예: １２０ｇ×３ → 360)
    pattern_mul = re.compile(
        r"([０-９0-9]+\.?[０-９0-9]*)([gGｇＧmMｍＭlLリットルﾘｯﾄﾙ個コ袋])\s*[×xX]\s*([０-９0-9]+)\s*$"
    )
    m = pattern_mul.search(name)
    if m:
        qty_s = m.group(1).translate(to_hankaku)
        unit = m.group(2)
        mult_s = m.group(3).translate(to_hankaku)
        try:
            qty_f = float(qty_s)
            mult_i = int(float(mult_s))
            total = int(qty_f * mult_i) if qty_f == int(qty_f) else qty_f * mult_i
            cap = str(total) if unit in ["g", "G", "ｇ", "Ｇ"] else f"{total}{unit}"
            return name[: m.start()].strip(), cap
        except (ValueError, TypeError):
            pass
    # 패턴2: 数字+単位 만 (기존)
    pattern = re.compile(
        r"([０-９0-9]+\.?[０-９0-9]*)([gGｇＧmMｍＭlLリットルﾘｯﾄﾙ個コ袋])\s*$"
    )
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
    제품명·용량 유사도를 각각 계산하고, 둘의 평균으로 정렬해 상위 top_k 반환.
    min_similarity 필터 없음(전수 계산 후 평균 기준 정렬만).
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"파일 없음: {csv_path}")
    df = pd.read_csv(csv_path, encoding="utf-8")
    # 제품코드·시키리·본부장이 모두 있는 행만 사용 → 매핑 결과에 NaN이 나오지 않도록
    df = df.dropna(subset=["제품코드", "시키리", "본부장"])
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
            avg = (primary_score + sub_score) / 2.0
            row_dict = {
                **row.to_dict(),
                f"{col}_similarity": round(primary_score, 4),
                f"{sub_col}_similarity": round(sub_score, 4),
                "_avg_similarity": round(avg, 4),
            }
            rows.append(row_dict)
        else:
            row_dict = {**row.to_dict(), "similarity": round(primary_score, 4)}
            rows.append(row_dict)

    if sub_col and sub_query is not None:
        rows.sort(key=lambda x: x.get("_avg_similarity", 0), reverse=True)
    else:
        rows.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return pd.DataFrame(rows).head(top_k)


def resolve_product_code(product_name: Optional[str], csv_path: Path) -> Optional[str]:
    """
    商品名으로 unit_price.csv 유사도 1위 매칭 후 商品CD(제품코드) 반환.
    최초 분석/DB 저장 전 商品CD 매핑용.
    """
    result = resolve_product_and_prices(product_name, csv_path)
    return result[0] if result else None


def resolve_product_and_prices(
    product_name: Optional[str], csv_path: Path
) -> Optional[Tuple[Optional[str], Optional[float], Optional[float]]]:
    """
    商品名으로 unit_price.csv 유사도 1위 매칭 후 (商品CD, 仕切, 本部長) 반환.
    최초 분석/DB 저장 전 商品CD·仕切·本部長 매핑용. NET는 仕切−条件로 계산하므로 별도 저장 안 함.
    반환: (商品CD, 仕切, 本部長) 또는 None
    """
    if not product_name or not str(product_name).strip():
        return None
    if not csv_path.exists():
        return None
    try:
        base_name, capacity = split_name_and_capacity(str(product_name))
        sub_query = capacity if capacity else None
        df = find_similar_products(
            query=base_name,
            csv_path=csv_path,
            col="제품명",
            top_k=1,
            min_similarity=0.2,
            sub_col="제품용량",
            sub_query=sub_query,
            sub_min_similarity=0.0,
        )
        if df.empty:
            return None
        row = df.iloc[0]
        pc = row.get("제품코드")
        code = str(pc).strip() if pc is not None else None
        shikiri_raw = row.get("시키리")
        honbu_raw = row.get("본부장")
        shikiri: Optional[float] = None
        if shikiri_raw is not None:
            try:
                shikiri = float(shikiri_raw)
            except (TypeError, ValueError):
                pass
        honbu: Optional[float] = None
        if honbu_raw is not None:
            try:
                honbu = float(honbu_raw)
            except (TypeError, ValueError):
                pass
        return (code, shikiri, honbu)
    except Exception:
        return None
