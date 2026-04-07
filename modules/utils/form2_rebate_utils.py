"""
양식지 조건/금액 2컬럼 + 최종합산 후처리 유틸.

- 정책: 저장은 null 유지, 계산 시 null/빈값은 0으로 간주
- 대상: 01/02/03/04/05 (유형별 키 매핑으로 처리)
- 양식 02는 기존 병합/분리 로직 유지
- 양식별 필드 매핑은 config/form_types.json에서 로드
"""

import json
import unicodedata
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── config/form_types.json 로드 ──────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "form_types.json"
_form_types_config: Dict[str, Any] = {}


def _load_form_types_config() -> Dict[str, Any]:
    """config/form_types.json을 읽어 캐싱. 서버 기동 시 1회만 로드."""
    global _form_types_config
    if _form_types_config:
        return _form_types_config
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        _form_types_config = json.load(f)
    return _form_types_config


def get_form_types_config() -> Dict[str, Any]:
    """외부에서 form_types config 전체를 참조할 때 사용."""
    return _load_form_types_config()


def _build_form_dual_key_map() -> Dict[str, Dict[str, str]]:
    """config/form_types.json의 fields 섹션으로 FORM_DUAL_KEY_MAP 동적 생성."""
    cfg = _load_form_types_config()
    result: Dict[str, Dict[str, str]] = {}
    for form_code, form_cfg in cfg.items():
        norm = str(form_code).lstrip("0") or form_code
        result[norm] = dict(form_cfg["fields"])
    return result


# 기존 코드 호환용 상수 (JSON에서 동적 로드)
FORM_DUAL_KEY_MAP = _build_form_dual_key_map()

AMOUNT_KEY = "金額"
AMOUNT2_KEY = "金額2"
FINAL_AMOUNT_KEY = "最終金額"
CONDITION_KEY = "条件"
CONDITION2_KEY = "条件2"
CALC_CONDITION_KEY = "計算条件（適用人数）"
QUANTITY_CONDITION_TOKEN = "数量条件"
TOTAL_QTY_KEY = "取引数量計"


def _dual_keys_display_order(form_type_norm: str) -> List[str]:
    """양식별 듀얼 컬럼 키 표시 순서. 예: 1 -> [条件, 条件2, 金額, 金額2, 最終金額]"""
    m = FORM_DUAL_KEY_MAP.get(form_type_norm)
    if not m:
        return []
    return [
        m["condition1"],
        m["condition2"],
        m["amount1"],
        m["amount2"],
        m["final_amount"],
    ]


def merge_item_data_keys_with_form_dual(
    keys: List[str],
    form_type: Optional[str],
    keys_in_db: set,
) -> List[str]:
    """
    documents.form_type 확정 후: 조건2·금액2·최종 계열을 양식별 고정 순으로 끼워 넣음.

    keys: 메타+extra 병합 직후 순서. keys_in_db: 해당 페이지 행들에 실제 존재하는 키(apply_form2 직후).
    """
    if not form_type or not keys:
        return keys
    ft = str(form_type).strip().lstrip("0") or ""
    dual_order = _dual_keys_display_order(ft)
    if not dual_order:
        return keys
    dual_set = set(dual_order)
    dual_present = [k for k in dual_order if k in keys_in_db]
    if not dual_present:
        return keys
    rest = [k for k in keys if k not in dual_set]
    fi = next((i for i, k in enumerate(keys) if k in dual_set), None)
    if fi is None:
        tail = [k for k in dual_present if k not in rest]
        return rest + tail
    non_dual_before = [k for k in keys[:fi] if k not in dual_set]
    insert_pos = len(non_dual_before)
    return rest[:insert_pos] + dual_present + rest[insert_pos:]


def _parse_amount(value: Any) -> float:
    """金額/金額2 값을 실수로 파싱. 전각 숫자·쉼표(NFKC) 후 반각 쉼표 제거."""
    if value is None:
        return 0.0
    s = unicodedata.normalize("NFKC", str(value)).replace(",", "").replace("，", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)  # 예: "123.45" -> 123.45 (소수점 유지)
    except (ValueError, TypeError):
        return 0.0


def _format_amount(value: float) -> str:
    """최종금액 문자열 포맷. 불필요한 소수점 0만 제거."""
    s = f"{value:.12f}".rstrip("0").rstrip(".")  # 예: 10.500000 -> "10.5", 100.000 -> "100"
    return s if s else "0"  # 예: 0.0 -> "0"


def _norm_text(value: Any) -> str:
    """문자열 정규화(NFKC). None/빈값은 빈 문자열."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip()
    if s.lower() in {"null", "none", "nan"}:
        return ""
    return s


def _is_blank_like(value: Any) -> bool:
    return _norm_text(value) == ""  # 예: None/"null"/"" -> True


def _extract_number_tokens(value: Any) -> List[str]:
    """
    문자열에서 숫자 토큰 추출.
    예: "604,800 139,200" -> ["604,800", "139,200"]
    """
    s = _norm_text(value)
    if not s:
        return []
    return re.findall(r"\d[\d,，]*(?:\.\d+)?", s)


def _split_dual_values_in_row(item: Dict[str, Any]) -> None:
    """
    한 셀에 2개 값이 들어온 경우 분리.
    - 金額: "604,800 139,200" -> 金額, 金額2
    - 条件: "126.00 29.00"    -> 条件, 条件2
    """
    if _norm_text(item.get(AMOUNT2_KEY)) == "":
        amount_tokens = _extract_number_tokens(item.get(AMOUNT_KEY))
        if len(amount_tokens) >= 2:
            item[AMOUNT_KEY] = amount_tokens[0]   # 예: "604,800"
            item[AMOUNT2_KEY] = amount_tokens[1]  # 예: "139,200"

    if _norm_text(item.get(CONDITION2_KEY)) == "":
        condition_tokens = _extract_number_tokens(item.get(CONDITION_KEY))
        if len(condition_tokens) >= 2:
            item[CONDITION_KEY] = condition_tokens[0]    # 예: "126.00"
            item[CONDITION2_KEY] = condition_tokens[1]   # 예: "29.00"


def _ensure_dual_keys_and_final(item: Dict[str, Any], form_type: Optional[str]) -> None:
    """유형별 ② 필드 기본값 보정(null) + 최종합산 계산."""
    if form_type is None or not isinstance(item, dict):
        return
    normalized_form_type = str(form_type).lstrip("0")
    key_map = FORM_DUAL_KEY_MAP.get(normalized_form_type)
    if not key_map:
        return

    c2_key = key_map["condition2"]  # str; 예: "条件2"
    a1_key = key_map["amount1"]     # str; 예: "金額" / "請求金額"
    a2_key = key_map["amount2"]     # str; 예: "金額2" / "請求金額2"
    final_key = key_map["final_amount"]  # str; 예: "最終金額"

    if c2_key not in item or _is_blank_like(item.get(c2_key)):
        item[c2_key] = None  # JSON null 유지
    if a2_key not in item or _is_blank_like(item.get(a2_key)):
        item[a2_key] = None  # JSON null 유지

    a1 = _parse_amount(item.get(a1_key))
    a2 = _parse_amount(item.get(a2_key))
    item[final_key] = _format_amount(a1 + a2)  # 계산시 null은 0으로 처리


def _is_non_quantity_condition_row(item: Dict[str, Any]) -> bool:
    """
    계산조건이 있고 '数量条件'이 아닌 행인지 판별.
    예: 計算条件（適用人数）='納価条件' / '金額条件' -> True
    """
    cond = _norm_text(item.get(CALC_CONDITION_KEY))
    return bool(cond) and QUANTITY_CONDITION_TOKEN not in cond


def _merge_with_previous_row(prev_item: Dict[str, Any], curr_item: Dict[str, Any]) -> None:
    """
    현재 행(curr)을 직전 행(prev)에 병합.
    - 금액: prev.金額2
    - 조건: prev.条件2
    - 계산조건: prev.計算条件（適用人数）에 curr 값을 합쳐 보존
    """
    prev_cond = _norm_text(prev_item.get(CALC_CONDITION_KEY))
    curr_cond = _norm_text(curr_item.get(CALC_CONDITION_KEY))
    if curr_cond:
        if prev_cond:
            if curr_cond not in prev_cond:
                prev_item[CALC_CONDITION_KEY] = f"{prev_cond} {curr_cond}"  # 예: '数量条件 納価条件'
        else:
            prev_item[CALC_CONDITION_KEY] = curr_cond  # 예: '' + '納価条件' -> '納価条件'

    if _norm_text(prev_item.get(CONDITION2_KEY)) == "":
        curr_condition_value = curr_item.get(CONDITION_KEY)
        if _norm_text(curr_condition_value) != "":
            prev_item[CONDITION2_KEY] = curr_condition_value  # 예: 条件2='29.00'

    if _norm_text(prev_item.get(AMOUNT2_KEY)) == "":
        curr_amount_value = curr_item.get(AMOUNT_KEY)
        if _norm_text(curr_amount_value) != "":
            prev_item[AMOUNT2_KEY] = curr_amount_value  # 예: 金額2='24,360'


def _merge_form2_rows_by_condition(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    양식 2번 상세행 병합:
    - 현재 행의 계산조건이 '数量条件'이 아니면, 해당 행을 직전 행에 병합.
    - 원본 item shape: Dict[str, Any]  # 예: {"計算条件（適用人数）":"納価条件","条件":"29.00","金額":"24,360"}
    """
    merged_items: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if merged_items and _is_non_quantity_condition_row(item):
            _merge_with_previous_row(merged_items[-1], item)
            continue
        merged_items.append(item)
    return merged_items


def infer_form_type_from_item(item: Dict[str, Any]) -> Optional[str]:
    """
    (백필·분석용) item 키로 양식 1~5 추정. config/form_types.json의
    inference_keys / inference_alt_keys / inference_priority 기반으로 동적 추론.

    priority 값이 낮을수록 우선 매칭. is_default_fallback=true인 양식은 최후 폴백.
    """
    if not isinstance(item, dict):
        return None
    keys = set(item.keys())
    cfg = _load_form_types_config()

    # priority 오름차순 정렬 (낮을수록 우선)
    sorted_forms = sorted(cfg.items(), key=lambda x: x[1].get("inference_priority", 99))

    default_fallback = None
    for form_code, form_cfg in sorted_forms:
        if form_cfg.get("is_default_fallback"):
            default_fallback = str(form_code).lstrip("0")
            continue

        inference_keys = form_cfg.get("inference_keys", [])
        # 메인 키 중 하나라도 item에 존재하거나 값이 있으면 매칭
        if any(k in keys or _norm_text(item.get(k)) for k in inference_keys):
            return str(form_code).lstrip("0")

        # alt_keys: 모든 키가 동시에 존재해야 매칭
        alt_keys = form_cfg.get("inference_alt_keys", [])
        if alt_keys and all(k in keys or _norm_text(item.get(k)) for k in alt_keys):
            return str(form_code).lstrip("0")

    # 폴백: default 양식 (01)
    if default_fallback:
        fallback_cfg = cfg.get(f"0{default_fallback}", cfg.get(default_fallback, {}))
        fallback_keys = fallback_cfg.get("inference_keys", [])
        if any(k in keys or _norm_text(item.get(k)) for k in fallback_keys):
            return default_fallback
    return None


def _fill_missing_amount2_from_qty_and_condition2(item: Dict[str, Any]) -> None:
    """
    금액2 누락 fallback:
    - 조건2는 있는데 금액2가 비어 있고
    - 수량(取引数量計) 파싱 가능하면
    => 금액2 = 수량 * 조건2 로 보정
    """
    if _norm_text(item.get(AMOUNT2_KEY)) != "":
        return
    if _norm_text(item.get(CONDITION2_KEY)) == "":
        return
    qty_tokens = _extract_number_tokens(item.get(TOTAL_QTY_KEY))
    qty_raw = qty_tokens[0] if qty_tokens else item.get(TOTAL_QTY_KEY)
    qty = _parse_amount(qty_raw)  # 예: "840" / "1,008" / "4,800 4,800" -> 첫 토큰 4800
    c2 = _parse_amount(item.get(CONDITION2_KEY))  # 예: "29.00" / "7.00"
    if qty <= 0 or c2 <= 0:
        return
    item[AMOUNT2_KEY] = _format_amount(qty * c2)  # 예: 840*29 -> "24360"


def apply_form2_final_amount_row(item: Dict[str, Any], form_type: Optional[str]) -> None:
    """
    양식 2번 1행: 最終金額 = 金額 + 金額2（金額2 欠損は 0）。

    DB 조회 응답·저장·파싱 후처리에서 공통 사용.
    documents.form_type 이 없으면 듀얼 키(条件2 등)를 넣지 않는다.
    """
    if not isinstance(item, dict):
        return
    if form_type is None or (isinstance(form_type, str) and not str(form_type).strip()):
        return
    normalized_form_type = str(form_type).lstrip("0")

    if normalized_form_type == "2":
        _split_dual_values_in_row(item)  # 예: "604,800 139,200" -> 金額/金額2
        _fill_missing_amount2_from_qty_and_condition2(item)  # 예: 840 * 29.00 -> "24360"

    _ensure_dual_keys_and_final(item, form_type)  # 01~05 공통; 条件2·金額2·最終金額 키 보장


def normalize_form2_rebate_conditions(
    page_results: List[Dict[str, Any]],
    form_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    양식지 2번 전용 후처리（ページ単位 items に apply_form2_final_amount_row を適用）。

    Args:
        page_results: 페이지별 결과 리스트 (각 요소는 {"items": [...]} 형태)
        form_type: 양식지 타입 (예: "01", "02" ...)

    Returns:
        수정된 page_results (in-place 수정, 동일 객체 반환)
    """
    if form_type is None:
        return page_results

    normalized_form_type = str(form_type).lstrip("0")
    if normalized_form_type not in {"1", "2", "3", "4", "5"}:
        return page_results

    if not page_results:
        return page_results

    for page in page_results:
        items = page.get("items") or []
        if not isinstance(items, list):
            continue

        if normalized_form_type == "2":
            # 규칙: '数量条件'이 아닌 행은 직전 행에 병합 (예: 納価条件, 金額条件 등)
            merged_items = _merge_form2_rows_by_condition(items)
            page["items"] = merged_items
        else:
            merged_items = items

        for item in merged_items:
            if not isinstance(item, dict):
                continue
            apply_form2_final_amount_row(item, form_type)

    return page_results
