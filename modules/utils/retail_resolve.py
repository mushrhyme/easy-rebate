"""
판매처·소매처 매핑 해소: 1) RAG(벡터 DB) 정답지 유사도, 2) 得意先コード→domae_retail_1, 3) retail_user 유사도, 4) domae_retail_2 유사도.
거래처명 있으면 1(RAG) 시도 → 실패 시 2→3→4. 得意先コード 있으면 2 시도 후 실패 시 3·4 중 유사도 높은 쪽.
"""
import json
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd

from modules.utils.config import get_project_root
from modules.utils.master_display_enrich import first_sap_dist_row as _first_sap_dist_row

_PROJECT_ROOT = get_project_root()
_RETAIL_USER_CSV = _PROJECT_ROOT / "database" / "csv" / "retail_user.csv"
_DOMAE_RETAIL_1_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_1.csv"
_DOMAE_RETAIL_2_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_2.csv"
_DIST_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "dist_retail.csv"
_SAP_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "sap_retail.csv"


def _dist_for_retail(retail_code: str) -> Tuple[str, str]:
    """소매처코드 → (판매처코드, 판매처명). sap_retail 우선."""
    _rn, dist_c, dist_n = _first_sap_dist_row(retail_code)
    return (dist_c, dist_n)


def parse_json_like(value: Any) -> Any:
    """문자열 JSON이면 객체로 복원, 아니면 원본 반환."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if not ((s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))):
        return value
    try:
        return json.loads(s)  # 예: '{"office_name":"岡山支店"}' -> {"office_name": "岡山支店"}
    except Exception:
        return value


def extract_office_name_from_issuer(issuer_value: Any) -> Optional[str]:
    """issuer(dict|string JSON)에서 office_name 추출."""
    parsed = parse_json_like(issuer_value)
    if isinstance(parsed, dict):
        v = parsed.get("office_name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def extract_cover_issuer_office_name(page_results: List[Dict[str, Any]]) -> Optional[str]:
    """문서 page_results에서 cover issuer.office_name 추출."""
    if not isinstance(page_results, list):
        return None
    for page in page_results:
        if not isinstance(page, dict):
            continue
        page_role = (page.get("page_role") or "").strip().lower()
        page_number = page.get("page_number")
        is_cover = page_role == "cover" or page_number == 1
        if not is_cover:
            continue
        office = extract_office_name_from_issuer(page.get("issuer"))
        if office:
            return office
    return None


def _dist_candidates_for_retail(retail_code: str) -> List[Tuple[str, str]]:
    """
    소매처코드 기준 판매처 후보 목록 반환.
    반환: [(판매처코드, 판매처명), ...] (중복 제거, 입력 순 유지)
    """
    code = (retail_code or "").strip()
    if not code:
        return []
    out: List[Tuple[str, str]] = []
    seen = set()
    for csv_path in (_SAP_RETAIL_CSV, _DIST_RETAIL_CSV):
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str)
        except Exception:
            continue
        for _, r in df.iterrows():
            rc = (r.get("소매처코드") or "").strip()
            if rc != code:
                continue
            dist_c = (r.get("판매처코드") or "").strip()
            dist_n = (r.get("판매처명") or "").strip()
            if not dist_c:
                continue
            key = (dist_c, dist_n)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def _resolve_dist_with_issuer_office(
    retail_code: Optional[str],
    form_type: Optional[str],
    issuer_office_name: Optional[str],
) -> Optional[str]:
    """
    양식지 01/03 한정:
    - 같은 소매처코드에 판매처 후보가 2개 이상이면 issuer.office_name과 판매처명 유사도 최댓값 선택.
    - 그 외에는 None 반환(기존 로직 유지 신호).
    """
    rc = (retail_code or "").strip()
    ft = (form_type or "").strip()
    office = (issuer_office_name or "").strip()
    if ft not in {"01", "03"}:
        return None
    if not rc or not office:
        return None
    candidates = _dist_candidates_for_retail(rc)
    if len(candidates) < 2:
        return None
    try:
        from database.db_manager import _similarity_difflib  # 지연 import
    except Exception:
        return None
    best_code = None
    best_score = -1.0
    for dist_c, dist_n in candidates:
        score = _similarity_difflib(office, (dist_n or "").strip())
        if score > best_score:
            best_score = score
            best_code = dist_c
    return best_code


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
    form_type: Optional[str] = None,
    issuer_office_name: Optional[str] = None,
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
            retail_code, dist_code = rag_result
            preferred = _resolve_dist_with_issuer_office(retail_code, form_type, issuer_office_name)
            if preferred:
                return (retail_code, preferred)
            return rag_result

    # 2순위: 得意先コード → domae_retail_1
    if code:
        one = _match_by_customer_code(code)
        if one is not None:
            retail_code, dist_code = one
            preferred = _resolve_dist_with_issuer_office(retail_code, form_type, issuer_office_name)
            if preferred:
                return (retail_code, preferred)
            return one

    # 3·4순위: retail_user / domae_retail_2 유사도
    r2, d2, s2 = _best_by_retail_user(name)
    r3, d3, s3 = _best_by_domae_retail_2(name)
    chosen: Optional[Tuple[Optional[str], Optional[str]]] = None
    if s2 >= s3 and r2 is not None:
        chosen = (r2, d2)
    elif s3 > s2 and r3 is not None:
        chosen = (r3, d3)
    elif r2 is not None:
        chosen = (r2, d2)
    elif r3 is not None:
        chosen = (r3, d3)
    if chosen is not None:
        retail_code, dist_code = chosen
        preferred = _resolve_dist_with_issuer_office(retail_code, form_type, issuer_office_name)
        if preferred:
            return (retail_code, preferred)
        return chosen
    return (None, None)
