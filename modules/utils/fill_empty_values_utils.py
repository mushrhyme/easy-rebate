"""
빈값 채우기 유틸리티 모듈

페이지별 JSON 결과에서 빈값을 채우는 로직을 제공합니다.
answer.json item 키는 양식 무관하게 통일: 請求番号, 得意先, 備考, 税額, 得意先コード 등.
1. 동일 페이지 내: 이전 아이템의 請求番号, 得意先, 得意先コード 로 빈칸 채우기
2. 페이지 간: 직전 페이지에서 請求番号/得意先/備考, 다음 페이지에서 税額를 가져와 채움.
"""

from typing import List, Dict, Any, Optional, Tuple

# 표준화된 item 키 (양식별 매핑 없음). 읽기 시 구 키(得意先コード) 폴백 지원.
KEY_MANAGEMENT_ID = "請求番号"
KEY_CUSTOMER = "得意先"
KEY_CUSTOMER_CODE = "得意先コード"
KEY_CUSTOMER_CODE_LEGACY = "得意先コード"  # 기존 JSON 호환용
KEY_SUMMARY = "備考"
KEY_TAX = "税額"

# 상동기호(〃)로 OCR이 읽은 문자열 → null로 치환 후 빈값 채우기에서 이전 행으로 채움
DITTO_LIKE_STRINGS = frozenset(("//", "1/", "11", "〃", "″"))
# 상동기호가 나올 수 있는 item 필드 (정규화 대상)
FIELDS_NORMALIZE_DITTO = ("商品名", "内入数", "商品コード")


def _is_ditto_like(value: Any) -> bool:
    """상동기호로 의심되는 값인지 (//, 1/, 11, 〃 등)."""
    if value is None:
        return False
    if isinstance(value, str):
        s = value.strip()
        return s in DITTO_LIKE_STRINGS or s == ""
    return False


def normalize_ditto_like_values_in_page_results(
    page_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    프롬프트로 해결 안 된 경우: items 내 商品名·内入数·商品コード가 상동기호(//, 11 등)로만 되어 있으면 null로 치환.
    빈값 채우기 직전에 호출할 것.
    """
    if not page_results:
        return page_results
    for page_json in page_results:
        items = page_json.get("items", [])
        for item in items:
            for key in FIELDS_NORMALIZE_DITTO:
                if key not in item:
                    continue
                if _is_ditto_like(item[key]):
                    item[key] = None
    return page_results


def _is_empty_value(value: Any) -> bool:
    """값이 비어있는지 확인."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() == "null"
    return False


def _get_field_value(item: Dict[str, Any], field_name: str) -> Optional[str]:
    """아이템에서 해당 필드값 조회. 비어있으면 None."""
    value = item.get(field_name)
    if _is_empty_value(value):
        return None
    return str(value).strip()


def _set_field_value(item: Dict[str, Any], field_name: str, value: str) -> None:
    """아이템에 필드값 설정 (기존 키 있으면 덮고, 없으면 추가)."""
    item[field_name] = value


def _get_last_values_from_page(
    page_json: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """페이지의 마지막 아이템에서 請求番号, 得意先, 備考 추출."""
    items = page_json.get("items", [])
    if not items:
        return (None, None, None)
    last_mgmt = None
    last_customer = None
    last_summary = None
    for item in reversed(items):
        if last_mgmt is None:
            last_mgmt = _get_field_value(item, KEY_MANAGEMENT_ID)
        if last_customer is None:
            last_customer = _get_field_value(item, KEY_CUSTOMER)
        if last_summary is None:
            last_summary = _get_field_value(item, KEY_SUMMARY)
        if last_mgmt is not None and last_customer is not None and last_summary is not None:
            break
    return (last_mgmt, last_customer, last_summary)


def _get_first_tax_from_page(page_json: Dict[str, Any]) -> Optional[str]:
    """페이지의 첫 번째 아이템에서 税額 추출."""
    items = page_json.get("items", [])
    if not items:
        return None
    for item in items:
        v = _get_field_value(item, KEY_TAX)
        if v:
            return v
    return None


def _fill_empty_values_within_page(items: List[Dict[str, Any]]) -> None:
    """
    동일 페이지 내에서 이전 아이템의 값으로 빈칸 채우기.
    請求番号, 得意先, 得意先コード + 商品名, 内入数, 商品コード(상동기호→null 후 이전 행으로 채움).
    """
    if not items:
        return

    current_mgmt = None
    current_customer = None
    current_customer_code = None
    # 상동기호→null 후 이전 행 값으로 채울 필드
    current_product_name = None
    current_naiiryu = None
    current_shohin_code = None

    for item in items:
        item_mgmt = _get_field_value(item, KEY_MANAGEMENT_ID)
        if item_mgmt:
            current_mgmt = item_mgmt
        elif current_mgmt:
            _set_field_value(item, KEY_MANAGEMENT_ID, current_mgmt)

        item_customer = _get_field_value(item, KEY_CUSTOMER)
        if item_customer:
            current_customer = item_customer
        elif current_customer:
            _set_field_value(item, KEY_CUSTOMER, current_customer)

        item_code = _get_field_value(item, KEY_CUSTOMER_CODE) or _get_field_value(item, KEY_CUSTOMER_CODE_LEGACY)
        if item_code:
            current_customer_code = item_code
        elif current_customer_code:
            _set_field_value(item, KEY_CUSTOMER_CODE, current_customer_code)

        # 商品名, 内入数, 商品コード: 비어 있으면 이전 행 값으로 채움 (상동기호→null 후)
        name_val = _get_field_value(item, "商品名")
        if name_val:
            current_product_name = name_val
        elif current_product_name:
            _set_field_value(item, "商品名", current_product_name)
        naiiryu_val = _get_field_value(item, "内入数")
        if naiiryu_val:
            current_naiiryu = naiiryu_val
        elif current_naiiryu:
            _set_field_value(item, "内入数", current_naiiryu)
        shohin_val = _get_field_value(item, "商品コード")
        if shohin_val:
            current_shohin_code = shohin_val
        elif current_shohin_code:
            _set_field_value(item, "商品コード", current_shohin_code)


def fill_empty_values_in_page_results(
    page_results: List[Dict[str, Any]],
    form_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    페이지별 JSON 결과에서 빈값 채우기.
    표준 키(請求番号, 得意先, 備考, 税額, 得意先コード) 기준으로 동작. form_type은 미사용(호환용).
    - 동일 페이지 내: 이전 아이템의 請求番号, 得意先, 得意先コード 로 빈칸 채우기
    - 페이지 간: 직전 페이지에서 請求番号/得意先/備考, 다음 페이지에서 税額를 가져와 채움.
    """
    if not page_results:
        return page_results

    total_pages = len(page_results)

    for page_idx, page_json in enumerate(page_results):
        items = page_json.get("items", [])
        if not items:
            continue
        current_page = page_idx + 1

        _fill_empty_values_within_page(items)

        last_mgmt, last_customer, last_summary = (None, None, None)
        if current_page > 1:
            last_mgmt, last_customer, last_summary = _get_last_values_from_page(page_results[page_idx - 1])

        first_tax = None
        if current_page < total_pages:
            first_tax = _get_first_tax_from_page(page_results[page_idx + 1])

        for item in items:
            if last_mgmt and _get_field_value(item, KEY_MANAGEMENT_ID) is None:
                _set_field_value(item, KEY_MANAGEMENT_ID, last_mgmt)
            if last_customer and _get_field_value(item, KEY_CUSTOMER) is None:
                _set_field_value(item, KEY_CUSTOMER, last_customer)
            if last_summary and _get_field_value(item, KEY_SUMMARY) is None:
                _set_field_value(item, KEY_SUMMARY, last_summary)
            if first_tax and _get_field_value(item, KEY_TAX) is None:
                _set_field_value(item, KEY_TAX, first_tax)

    return page_results
