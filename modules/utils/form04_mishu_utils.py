"""
3·4번 양식 전용: 未収条件를 뒤에서 2째 자리에 소수점을 넣어 DB 저장용 문자열로 변환

- 적용 시점: answer-json 저장 시, create-items-from-answer, save_document_data, sync_img_pages
- 규칙: 1000 → "10.00", 370 → "3.70" (값/100, 소수 둘째자리)
- item_dict in-place 수정
"""

import re
from typing import Any, Dict, Optional, Tuple


_DEC_SEPARATORS = r"[.\uFF0E\u00B7]"  # . / ．(전각) / ·(중간점)
_NUM_TOKEN_RE = re.compile(
    rf"\d+(?:,\d{{3}})*(?:{_DEC_SEPARATORS}\d+)?"
)


def _parse_num_token_and_has_decimal(v: Any) -> Tuple[Optional[float], bool]:
    """
    문자열/숫자에서 '첫 숫자 토큰'만 추출해 float로 파싱.

    Returns:
      (num, has_decimal)
      - has_decimal: 토큰 자체에 소수점(.,．,·) 구분자가 있었는지 여부
    """
    if v is None:
        return None, False

    if isinstance(v, int):
        # 숫자 타입(int)으로 들어오면 원본(raw=OCR 합침)으로 간주하고 /100을 수행
        return float(v), False
    if isinstance(v, float):
        # 숫자 타입(float)으로 들어오면 프론트/사용자 편집 결과일 가능성이 높으므로
        # "이미 정규화됨"으로 간주하고 소수표기만 포맷 통일
        return float(v), True

    s = str(v).strip()
    if not s:
        return None, False
    # 회계 점선 ':'가 문자열 내부에 남아있는 경우:
    # 예: "128:00円" / "1:608個" -> "12800円" / "1608個"
    # 이후 여기서는 "token에 소수점(.)이 있으면 이미 정규화됨" 정책을 사용합니다.
    s = re.sub(r"(\d+):(\d{2,4})", r"\1\2", s)

    m = _NUM_TOKEN_RE.search(s)
    if not m:
        return None, False

    token = m.group(0)
    has_decimal = any(sep in token for sep in [".", "\uFF0E", "\u00B7"])

    # 파싱 안정화를 위해 구분자 정규화 + 천단위 콤마 제거
    token_norm = token.replace(",", "").replace("\uFF0E", ".").replace("\u00B7", ".")
    try:
        return float(token_norm), has_decimal
    except (ValueError, TypeError):
        return None, False


def apply_form04_mishu_decimal(
    item_dict: Dict[str, Any],
    form_type: Optional[str],
) -> None:
    """
    3·4번 양식일 때 未収条件를 뒤에서 2째 자리 소수점 형식으로 변환 (in-place).
    예: "1000" → "10.00", "370" → "3.70"
    - form_type: "03", "3", "04", "4" 또는 int 3, 4
    - '未収条件' 값의 숫자 토큰에 소수점(., ．, ·)이 있으면 이미 정규화된 값으로 간주하고 /100 변환을 생략
    """
    ft = str(form_type or "").strip()
    if ft not in ("04", "4", "03", "3"):
        return
    key = "未収条件"
    v = item_dict.get(key)
    num, has_decimal = _parse_num_token_and_has_decimal(v)
    if num is None:
        return

    # 데이터 흐름:
    # - raw(OCR): "13400" (예: "134(점선)00" -> OCR 합침)
    # - normalized(LMM/사용자): "134.00" 또는 "134.0"/"134.00円" 같이 토큰에 소수점 포함
    # 정책:
    # - 토큰에 소수점이 있으면: /100 변환을 생략하고 "xx.xx" 포맷만 통일
    # - 소수점이 없으면: raw로 보고 /100 변환 후 "xx.xx" 포맷
    if has_decimal:
        # 예: "145.00" / "134.0" / "145.00円" -> "145.00" / "134.00" / "145.00"
        item_dict[key] = f"{num:.2f}"
    else:
        # 예: "14500" / "13900" -> "145.00" / "139.00"
        item_dict[key] = f"{num / 100:.2f}"
