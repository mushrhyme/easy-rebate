"""
판매처·소매처 매핑 해소: 1) RAG(벡터 DB) 정답지 유사도, 2) 得意先コード→domae_retail_1, 3) retail_user 유사도, 4) domae_retail_2 유사도.
거래처명 있으면 1(RAG) 시도 → 실패 시 2→3→4. 得意先コード 있으면 2 시도 후 실패 시 3·4 중 유사도 높은 쪽.
"""
from typing import Optional, Tuple

import pandas as pd

from modules.utils.config import get_project_root
from modules.utils.master_display_enrich import first_sap_dist_row as _first_sap_dist_row

_PROJECT_ROOT = get_project_root()
_RETAIL_USER_CSV = _PROJECT_ROOT / "database" / "csv" / "retail_user.csv"
_DOMAE_RETAIL_1_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_1.csv"
_DOMAE_RETAIL_2_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_2.csv"


def _dist_for_retail(retail_code: str) -> Tuple[str, str]:
    """소매처코드 → (판매처코드, 판매처명). sap_retail 우선."""
    _rn, dist_c, dist_n = _first_sap_dist_row(retail_code)
    return (dist_c, dist_n)


def _match_by_customer_code(customer_code: str) -> Optional[Tuple[str, str]]:
    """2) 得意先コード → domae_retail_1. 성공 시 (소매처코드, 판매처코드) 반환."""
    code = (customer_code or "").strip()
    if not code or not _DOMAE_RETAIL_1_CSV.exists():
        return None
    try:
        df = pd.read_csv(_DOMAE_RETAIL_1_CSV, dtype=str)
        row = df[df["도매소매처코드"].astype(str).str.strip() == code]
        if row.empty:
            return None
        r = row.iloc[0]
        retail_code = (r.get("소매처코드") or "").strip()
        if not retail_code:
            return None
        dist_c, _ = _dist_for_retail(retail_code)
        return (retail_code, dist_c)
    except Exception:
        return None


def _best_by_retail_user(customer_name: str) -> Tuple[Optional[str], Optional[str], float]:
    """3) retail_user 소매처명 유사도 1위. (소매처코드, 판매처코드, score)."""
    from database.db_manager import _similarity_difflib  # 순환 import 방지(지연)

    name = (customer_name or "").strip()
    if not name or not _RETAIL_USER_CSV.exists():
        return (None, None, 0.0)
    try:
        df = pd.read_csv(_RETAIL_USER_CSV, dtype=str)
        best_score = 0.0
        best_retail_code: Optional[str] = None
        for _, r in df.iterrows():
            n = (r.get("소매처명") or "").strip()
            c = (r.get("소매처코드") or "").strip()
            if not n or not c:
                continue
            score = _similarity_difflib(name, n)
            if score > best_score:
                best_score = score
                best_retail_code = c
        if not best_retail_code:
            return (None, None, 0.0)
        dist_c, _ = _dist_for_retail(best_retail_code)
        return (best_retail_code, dist_c or None, best_score)
    except Exception:
        return (None, None, 0.0)


def _best_by_domae_retail_2(customer_name: str) -> Tuple[Optional[str], Optional[str], float]:
    """4) domae_retail_2 도매소매처명/소매처명 유사도 1위. (소매처코드, 판매처코드, score)."""
    from database.db_manager import _similarity_difflib  # 순환 import 방지(지연)

    name = (customer_name or "").strip()
    if not name or not _DOMAE_RETAIL_2_CSV.exists():
        return (None, None, 0.0)
    try:
        df = pd.read_csv(_DOMAE_RETAIL_2_CSV, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        cols = list(df.columns)
        best_score = 0.0
        best_retail_code: Optional[str] = None
        for _, r in df.iterrows():
            domae_name = (str(r.iloc[0]) if cols else "") or ""
            domae_name = (domae_name or "").strip()
            code = (r.get("소매처코드") or "").strip()
            retail_name = (r.get("소매처명") or "").strip()
            if code and retail_name:
                if retail_name.isdigit() and len(retail_name) >= 4 and (not code.isdigit() or "■" in code):
                    code, retail_name = retail_name, code
            if not code:
                continue
            score = _similarity_difflib(name, domae_name or retail_name)
            if score > best_score:
                best_score = score
                best_retail_code = code
        if not best_retail_code:
            return (None, None, 0.0)
        dist_c, _ = _dist_for_retail(best_retail_code)
        return (best_retail_code, dist_c or None, best_score)
    except Exception:
        return (None, None, 0.0)


def _match_by_rag(customer_name: str) -> Optional[Tuple[str, str]]:
    """1순위: RAG(벡터 DB) 정답지 유사도. 성공 시 (소매처코드, 판매처코드) 반환."""
    name = (customer_name or "").strip()
    if not name:
        return None
    try:
        from modules.core.rag_manager import get_rag_manager
        rag = get_rag_manager(use_db=True)
        results = rag.search_retail_rag_answer(name, top_k=1, min_similarity=0.5)
        if results and len(results) > 0:
            r = results[0]
            retail = (r.get("小売先コード") or "").strip()
            dist = (r.get("受注先コード") or "").strip()
            if retail and dist:
                return (retail, dist)
    except Exception:
        pass
    return None


def resolve_retail_dist(
    customer_name: Optional[str] = None,
    customer_code: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    得意先(명)과 得意先コード(있으면)로 소매처코드·판매처코드 확정.
    - 1순위: 거래처명 있으면 RAG(벡터 DB) 정답지 유사도 → 성공 시 반환.
    - 2순위: 得意先コード 있으면 domae_retail_1 → 성공 시 반환.
    - 3·4순위: retail_user / domae_retail_2 유사도 높은 쪽.
    반환: (小売先コード=소매처코드, 受注先コード=판매처코드). 없으면 (None, None).
    """
    name = (customer_name or "").strip()
    code = (customer_code or "").strip() if customer_code else ""

    # 1순위: RAG(벡터 DB) 정답지
    if name:
        rag_result = _match_by_rag(name)
        if rag_result is not None:
            return rag_result

    # 2순위: 得意先コード → domae_retail_1
    if code:
        one = _match_by_customer_code(code)
        if one is not None:
            return one

    # 3·4순위: retail_user / domae_retail_2 유사도
    r2, d2, s2 = _best_by_retail_user(name)
    r3, d3, s3 = _best_by_domae_retail_2(name)
    if s2 >= s3 and r2 is not None:
        return (r2, d2)
    if s3 > s2 and r3 is not None:
        return (r3, d3)
    if r2 is not None:
        return (r2, d2)
    if r3 is not None:
        return (r3, d3)
    return (None, None)
