"""
3·4번 양식 전용: 未収条件를 뒤에서 2째 자리에 소수점을 넣어 DB 저장용 문자열로 변환

- 적용 시점: answer-json 저장 시, create-items-from-answer, save_document_data, sync_img_pages
- 규칙: 1000 → "10.00", 370 → "3.70" (값/100, 소수 둘째자리)
- item_dict in-place 수정
"""

from typing import Any, Dict, Optional


def _parse_num(v: Any) -> Optional[float]:
    """문자열/숫자 → float. None·빈문자·변환 실패 시 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if (v == v) else None
    s = str(v).strip().replace(",", "").replace("．", ".").replace("·", ".")
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def apply_form04_mishu_decimal(
    item_dict: Dict[str, Any],
    form_type: Optional[str],
) -> None:
    """
    3·4번 양식일 때 未収条件를 뒤에서 2째 자리 소수점 형식으로 변환 (in-place).
    예: "1000" → "10.00", "370" → "3.70"
    - form_type: "03", "3", "04", "4" 또는 int 3, 4
    - 이미 100 미만 값(소수 형태)은 변환하지 않음 (이중 변환 방지)
    """
    ft = str(form_type or "").strip()
    if ft not in ("04", "4", "03", "3"):
        return
    key = "未収条件"
    v = item_dict.get(key)
    num = _parse_num(v)
    if num is None:
        return
    # 이미 소수 형태(100 미만)면 변환 스킵. 예: "3.70" → 그대로
    if num < 100:
        return
    # 값/100, 소수 둘째자리 문자열 (예: 1000 → "10.00", 370 → "3.70")
    item_dict[key] = f"{num / 100:.2f}"
