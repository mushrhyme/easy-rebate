"""
양식지 2번 전용 후처리 유틸

- 対象: 양식지 2번 (form_type == "02")
- 全行: 最終金額 = 金額 + 金額2（金額2 が null/空/欠損は 0。金額・金額2は上書きしない）
- 旧パイプラインで 金額 に合算されていたデータは、元の分割は復元できない（再取込・手修正が必要）

page_results 구조: RAG 파서와 동일, 각 페이지 {"items": [...]} 형태.
"""

import unicodedata
import re
from typing import Any, Dict, List, Optional

AMOUNT_KEY = "金額"
AMOUNT2_KEY = "金額2"
FINAL_AMOUNT_KEY = "最終金額"
CONDITION_KEY = "条件"
CONDITION2_KEY = "条件2"
CALC_CONDITION_KEY = "計算条件（適用人数）"
QUANTITY_CONDITION_TOKEN = "数量条件"
TOTAL_QTY_KEY = "取引数量計"


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
    """
    if form_type is None:
        return
    if str(form_type).lstrip("0") != "2":
        return
    if not isinstance(item, dict):
        return

    _split_dual_values_in_row(item)  # 예: 金額="604,800 139,200" -> 金額/金額2 분리
    _fill_missing_amount2_from_qty_and_condition2(item)  # 예: 金額2=None, 条件2=29.00 -> 取引数量計*条件2

    a1 = _parse_amount(item.get(AMOUNT_KEY))
    a2 = _parse_amount(item.get(AMOUNT2_KEY))
    item[FINAL_AMOUNT_KEY] = _format_amount(a1 + a2)  # 예: 100.2 + 0.3 -> "100.5"


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
    if normalized_form_type != "2":
        return page_results

    if not page_results:
        return page_results

    for page in page_results:
        items = page.get("items") or []
        if not isinstance(items, list):
            continue

        # 규칙: '数量条件'이 아닌 행은 직전 행에 병합 (예: 納価条件, 金額条件 등)
        merged_items = _merge_form2_rows_by_condition(items)
        page["items"] = merged_items

        for item in merged_items:
            if not isinstance(item, dict):
                continue
            apply_form2_final_amount_row(item, form_type)

    return page_results
