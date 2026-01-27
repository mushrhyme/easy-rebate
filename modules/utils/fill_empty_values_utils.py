"""
빈값 채우기 유틸리티 모듈

페이지별 JSON 결과에서 빈값을 채우는 로직을 제공합니다.
1. 동일 페이지 내: 이전 아이템의 customer, customer_code, management_id로 빈칸 채우기
2. 페이지 간: 직전 페이지에서 관리번호, 거래처명, 摘要를 가져오고,
   다음 페이지에서 세액을 가져와서 채웁니다.

config.form_field_mapping 에서 form_type 별 필드명을 조회하며,
해당 form_type 에 대응되는 키가 없으면(get → None/빈값) 그 필드는 빈칸 채우기 하지 않음.
"""

from typing import List, Dict, Any, Optional, Tuple

from modules.utils.config import rag_config


def _normalize_form_type(form_type: Optional[str]) -> Optional[str]:
    """form_type 을 '01'~'05' 형태로 정규화. None/미지원이면 None."""
    if form_type is None:
        return None
    s = str(form_type).strip()
    if not s:
        return None
    if len(s) == 1 and s.isdigit():
        return s.zfill(2)
    if s in ("01", "02", "03", "04", "05"):
        return s
    return None


def _get_field_name_for_form(logical_key: str, form_type: Optional[str]) -> Optional[str]:
    """
    config.form_field_mapping[logical_key][form_type] 조회.
    키가 없거나 값이 비어있으면 None → 해당 필드는 빈칸 채우기 안 함.
    """
    ft = _normalize_form_type(form_type)
    if not ft:
        return None
    mapping = getattr(rag_config, "form_field_mapping", {}) or {}
    per_form = mapping.get(logical_key) or {}
    raw = per_form.get(ft)
    if raw is None:
        return None
    v = str(raw).strip() if raw else ""
    return v or None


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
    mgmt_fn: Optional[str],
    customer_fn: Optional[str],
    summary_fn: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    페이지의 마지막 아이템에서 관리번호, 거래처명, 摘要 추출.
    fn 이 None 인 필드는 추출하지 않음.
    """
    items = page_json.get("items", [])
    if not items:
        return (None, None, None)
    last_mgmt = None
    last_customer = None
    last_summary = None
    for item in reversed(items):
        if mgmt_fn and last_mgmt is None:
            last_mgmt = _get_field_value(item, mgmt_fn)
        if customer_fn and last_customer is None:
            last_customer = _get_field_value(item, customer_fn)
        if summary_fn and last_summary is None:
            last_summary = _get_field_value(item, summary_fn)
        done_m = last_mgmt is not None or not mgmt_fn
        done_c = last_customer is not None or not customer_fn
        done_s = last_summary is not None or not summary_fn
        if done_m and done_c and done_s:
            break
    return (last_mgmt, last_customer, last_summary)


def _get_first_tax_from_page(page_json: Dict[str, Any], tax_fn: Optional[str]) -> Optional[str]:
    """페이지의 첫 번째 아이템에서 세액 추출. tax_fn 없으면 None."""
    if not tax_fn:
        return None
    items = page_json.get("items", [])
    if not items:
        return None
    for item in items:
        v = _get_field_value(item, tax_fn)
        if v:
            return v
    return None


def _fill_empty_values_within_page(
    items: List[Dict[str, Any]],
    mgmt_fn: Optional[str],
    customer_fn: Optional[str],
    customer_code_fn: Optional[str],
) -> None:
    """
    동일 페이지 내에서 이전 아이템의 값으로 빈칸 채우기.
    
    customer, customer_code, management_id에 한해서
    이전 아이템에서 가장 최근에 채워진 값을 사용하여 빈칸을 채움.
    """
    if not items:
        return
    
    # 현재까지 채워진 값들을 추적
    current_mgmt = None
    current_customer = None
    current_customer_code = None
    
    for item in items:
        # management_id 채우기
        if mgmt_fn:
            item_mgmt = _get_field_value(item, mgmt_fn)
            if item_mgmt:
                current_mgmt = item_mgmt
            elif current_mgmt:
                _set_field_value(item, mgmt_fn, current_mgmt)
        
        # customer 채우기
        if customer_fn:
            item_customer = _get_field_value(item, customer_fn)
            if item_customer:
                current_customer = item_customer
            elif current_customer:
                _set_field_value(item, customer_fn, current_customer)
        
        # customer_code 채우기
        if customer_code_fn:
            item_customer_code = _get_field_value(item, customer_code_fn)
            if item_customer_code:
                current_customer_code = item_customer_code
            elif current_customer_code:
                _set_field_value(item, customer_code_fn, current_customer_code)


def fill_empty_values_in_page_results(
    page_results: List[Dict[str, Any]],
    form_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    페이지별 JSON 결과에서 빈값 채우기.

    - form_type 별로 config.form_field_mapping 조회.
    - get(form_type) 이 None/빈값이면 해당 필드는 채우기 안 함.
    - 동일 페이지 내: 이전 아이템의 customer, customer_code, management_id로 빈칸 채우기
    - 페이지 간: 직전 페이지에서 관리번호/거래처명/摘要, 다음 페이지에서 세액을 가져와 채움.
    """
    if not page_results:
        return page_results

    mgmt_fn = _get_field_name_for_form("management_id", form_type)
    customer_fn = _get_field_name_for_form("customer", form_type)
    customer_code_fn = _get_field_name_for_form("customer_code", form_type)
    summary_fn = _get_field_name_for_form("summary", form_type)
    tax_fn = _get_field_name_for_form("tax", form_type)

    use_prev = mgmt_fn or customer_fn or summary_fn
    total_pages = len(page_results)

    for page_idx, page_json in enumerate(page_results):
        items = page_json.get("items", [])
        if not items:
            continue
        current_page = page_idx + 1

        # 1. 동일 페이지 내 빈칸 채우기 (customer, customer_code, management_id)
        _fill_empty_values_within_page(items, mgmt_fn, customer_fn, customer_code_fn)

        # 2. 페이지 간 빈칸 채우기
        last_mgmt = None
        last_customer = None
        last_summary = None
        if use_prev and current_page > 1:
            prev = page_results[page_idx - 1]
            last_mgmt, last_customer, last_summary = _get_last_values_from_page(
                prev, mgmt_fn, customer_fn, summary_fn
            )

        first_tax = None
        if tax_fn and current_page < total_pages:
            nxt = page_results[page_idx + 1]
            first_tax = _get_first_tax_from_page(nxt, tax_fn)

        for item in items:
            if mgmt_fn and last_mgmt and _get_field_value(item, mgmt_fn) is None:
                _set_field_value(item, mgmt_fn, last_mgmt)
            if customer_fn and last_customer and _get_field_value(item, customer_fn) is None:
                _set_field_value(item, customer_fn, last_customer)
            if summary_fn and last_summary and _get_field_value(item, summary_fn) is None:
                _set_field_value(item, summary_fn, last_summary)
            if tax_fn and first_tax and _get_field_value(item, tax_fn) is None:
                _set_field_value(item, tax_fn, first_tax)

    return page_results
