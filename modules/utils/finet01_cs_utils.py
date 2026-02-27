"""
FINET 1번 양식지 전용 후처리: 数量単位=CS일 때 仕切・本部長에 入数 곱셈

- 적용 시점: 최초 분석 후 DB 저장 전, 매핑 모달에서 answer-json 저장 시
- 조건: upload_channel=finet, form_type=01, 数量単位=CS, 入数 유효값
- 동작: item_dict 내 仕切, 本部長에 入数를 곱한 값으로 갱신 (원본 dict in-place 수정)
"""

from typing import Any, Dict, Optional


def _parse_num(v: Any) -> Optional[float]:
    """문자열/숫자 → float. None·빈문자·변환 실패 시 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if (v == v) else None  # NaN 방지
    s = str(v).strip().replace(",", "").replace("．", ".").replace("·", ".")
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def apply_finet01_cs_irisu(
    item_dict: Dict[str, Any],
    form_type: Optional[str],
    upload_channel: Optional[str],
) -> None:
    """
    FINET 01이고 数量単位가 CS일 때 仕切・本部長에 入数 곱셈 적용 (in-place).

    Args:
        item_dict: 한 행 아이템 딕셔너리 (仕切, 本部長, 入数, 数量単位 등)
        form_type: 양식지 번호 (예: "01")
        upload_channel: 업로드 채널 ("finet" | "mail")
    """
    if upload_channel != "finet" or (form_type or "").strip() != "01":
        return
    if (item_dict.get("数量単位") or "").strip() != "CS":
        return
    irisu = _parse_num(item_dict.get("入数"))
    if irisu is None or irisu <= 0:
        return
    for key in ("仕切", "本部長"):
        val = item_dict.get(key)
        num = _parse_num(val)
        if num is not None:
            item_dict[key] = round(num * irisu, 2)
