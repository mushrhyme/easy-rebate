"""
양식지 2번 전용 리베이트 조건 후처리 유틸

- 対象: 양식지 2번 (form_type == "02")
- 조건:
    リベート計算条件（適用人数） == "納価条件" 인 경우
- 처리:
    取引数量合計（総数:内数） 값을 "0" 으로 강제 세팅

page_results 구조는 RAG 파서에서 내려주는 것과 동일하게
각 페이지가 {"items": [...]} 형태의 딕셔너리라고 가정한다.
"""

from typing import Any, Dict, List, Optional


# 리베이트 계산조건 필드명 후보
REBATE_CONDITION_FIELD_NAMES = [
    "リベート計算条件（適用人数）",
    "リベート計算条件(適用人数)",
    "リベート計算条件（適用入数）",
    "リベート計算条件(適用入数)",
    "リベート 計算条件 (適用入数)",
]

# 取引数量合計 필드명 후보
TOTAL_QUANTITY_FIELD_NAMES = [
    "取引数量合計（総数:内数）",
    "取引数量合計 (総数:内数)",
    "取引数量合計(総数:内数)",
]


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
    # 숫자 등은 문자열로 캐스팅
    text = str(value).strip()
    return text or None


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
    양식지 2번 전용 리베이트 조건 후처리.

    - 대상: form_type 이 "02" / "2" / 2 인 경우만 처리
    - 로직:
        리베ート計算条件(適用人数/適用入数) 가 "納価条件" 인 행은
        取引数量合計（総数:内数）를 "0" 으로 덮어쓴다.

    Args:
        page_results: 페이지별 결과 리스트 (각 요소는 {"items": [...]} 형태)
        form_type: 양식지 타입 (예: "01", "02" ...)

    Returns:
        수정된 page_results (in-place 로도 수정되지만, 동일 객체를 반환)
    """
    # form_type 이 2번이 아니면 아무 것도 하지 않고 그대로 반환
    if form_type is None:
        return page_results

    normalized_form_type = str(form_type).lstrip("0")  # "02" -> "2"
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

            # 리베이트 계산조건 필드 찾기
            condition_key = _get_first_existing_key(item, REBATE_CONDITION_FIELD_NAMES)
            if not condition_key:
                continue

            condition_value = _get_str_value(item, condition_key)
            if condition_value != "納価条件":
                continue

            # 取引数量合計 필드 찾기
            quantity_key = _get_first_existing_key(item, TOTAL_QUANTITY_FIELD_NAMES)
            if not quantity_key:
                # 필드가 아예 없으면 생성은 하지 않는다 (명시된 케이스만 0 세팅)
                continue

            # 문자열 "0" 으로 덮어쓰기 (원본 JSON이 문자열 숫자이므로)
            item[quantity_key] = "0"

    return page_results

