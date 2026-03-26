"""
sap/dist·unit_price 마스터로 그리드 표시용 명칭(受注先·小売先·マスタ商品名) 채움.
db_manager를 거치지 않아 순환 import 방지.

정책: 각 명칭 필드가 비어 있을 때만 마스터 조회값으로 채운다(모달·수정 반영 유지).
"""
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from modules.utils.config import get_project_root

_PROJECT_ROOT = get_project_root()
_DIST_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "dist_retail.csv"
_SAP_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "sap_retail.csv"


def _is_blank_name(item_dict: Dict[str, Any], key: str) -> bool:
    """명칭 컬럼이 비어 있으면 True — 예: None, '', 공백만."""
    v = item_dict.get(key)
    if v is None:
        return True
    return not str(v).strip()


def first_sap_dist_row(retail_code: str) -> Tuple[str, str, str]:
    """
    소매처코드 일치 첫 행(sap_retail → dist_retail). 1:N 시 첫 행만 사용.
    반환: (소매처명, 판매처코드, 판매처명).
    """
    code = (retail_code or "").strip()
    if not code:
        return ("", "", "")
    for csv_path in (_SAP_RETAIL_CSV, _DIST_RETAIL_CSV):
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str)
            for _, r in df.iterrows():
                retail = (r.get("소매처코드") or "").strip()
                if retail == code:
                    return (
                        (r.get("소매처명") or "").strip(),
                        (r.get("판매처코드") or "").strip(),
                        (r.get("판매처명") or "").strip(),
                    )
        except Exception:
            continue
    return ("", "", "")


def enrich_master_fields_from_codes(
    item_dict: Dict[str, Any],
    unit_price_csv: Optional[Path] = None,
) -> None:
    """
    小売先コード·商品コード가 있으면 마스터에서 명칭을 채운다.
    정책: 受注先·小売先·マスタ商品名은 각각 값이 비어 있을 때만 채운다(기존 값 덮어쓰지 않음).
    """
    rc = (item_dict.get("小売先コード") or item_dict.get("小売先CD") or "").strip()
    if rc:
        retail_name, _, dist_name = first_sap_dist_row(rc)
        if _is_blank_name(item_dict, "小売先"):
            item_dict["小売先"] = retail_name
        if _is_blank_name(item_dict, "受注先"):
            item_dict["受注先"] = dist_name
    pc = (item_dict.get("商品コード") or item_dict.get("商品CD") or "").strip()
    if pc and unit_price_csv is not None and _is_blank_name(item_dict, "マスタ商品名"):
        try:
            from backend.unit_price_lookup import lookup_product_name_by_code

            mname = lookup_product_name_by_code(pc, unit_price_csv)
            if mname:
                item_dict["マスタ商品名"] = mname
        except Exception:
            pass
