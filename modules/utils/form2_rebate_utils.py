"""
양식지 2번 전용 후처리 유틸

- 対象: 양식지 2번 (form_type == "02")
- 条件: 計算条件（適用人数） == "納価条件" 인 행
- 処理: 金額 + 金額2 를 金額에 합산, 金額2 키 삭제 (DB 저장·검토 탭에서 동일 데이터 사용)

page_results 구조: RAG 파서와 동일, 각 페이지 {"items": [...]} 형태.
"""

from typing import Any, Dict, List, Optional


# 計算条件 필드명 후보 (納価条件 체크용)
CONDITION_FIELD_NAMES = [
    "計算条件（適用人数）",
    "計算条件(適用人数)",
    "リベート計算条件（適用人数）",
    "リベート計算条件(適用人数)",
]

# 金額 필드명
AMOUNT_KEY = "金額"
AMOUNT2_KEY = "金額2"


def _get_str_value(item: Dict[str, Any], key: str) -> Optional[str]:
    """item[key] 를 문자열로 안전하게 가져오기."""
    if key not in item:
        return None
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _parse_amount(value: Any) -> int:
    """金額/金額2 값을 정수로 파싱 (쉼표 제거)."""
    if value is None:
        return 0
    s = str(value).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _get_first_existing_key(item: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """item 에서 존재하는 첫 번째 키를 반환."""
    for key in candidates:
        if key in item:
            return key
    return None


def normalize_form2_rebate_conditions(
    page_results: List[Dict[str, Any]],
    form_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    양식지 2번 전용 후처리.

    - 対象: form_type 이 "02" / "2" / 2 인 경우만 처리
    - ロ직: 計算条件（適用人数） 가 "納価条件" 인 행은
      金額 = 金額 + 金額2 로 합산하고, 金額2 키를 삭제한다.

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

        for item in items:
            if not isinstance(item, dict):
                continue

            condition_key = _get_first_existing_key(item, CONDITION_FIELD_NAMES)
            if not condition_key:
                continue

            condition_value = _get_str_value(item, condition_key)
            if condition_value != "納価条件":
                continue

            # 金額 + 金額2 합산 후 金額에 저장
            amount1 = _parse_amount(item.get(AMOUNT_KEY))
            amount2 = _parse_amount(item.get(AMOUNT2_KEY))
            item[AMOUNT_KEY] = str(amount1 + amount2)

            # 金額2 키 삭제 (검토 탭/DB에서 사용하지 않음)
            if AMOUNT2_KEY in item:
                del item[AMOUNT2_KEY]

    return page_results
