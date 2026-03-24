"""
양식지 2번 전용 후처리 유틸

- 対象: 양식지 2번 (form_type == "02")
- 全行: 最終金額 = 金額 + 金額2（金額2 が null/空/欠損は 0。金額・金額2は上書きしない）
- 旧パイプラインで 金額 に合算されていたデータは、元の分割は復元できない（再取込・手修正が必要）

page_results 구조: RAG 파서와 동일, 각 페이지 {"items": [...]} 형태.
"""

import unicodedata
from typing import Any, Dict, List, Optional

AMOUNT_KEY = "金額"
AMOUNT2_KEY = "金額2"
FINAL_AMOUNT_KEY = "最終金額"


def _parse_amount(value: Any) -> int:
    """金額/金額2 값을 정수로 파싱. 전각 숫자·쉼표(NFKC) 후 반각 쉼표 제거."""
    if value is None:
        return 0
    s = unicodedata.normalize("NFKC", str(value)).replace(",", "").replace("，", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


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

    a1 = _parse_amount(item.get(AMOUNT_KEY))
    a2 = _parse_amount(item.get(AMOUNT2_KEY))
    item[FINAL_AMOUNT_KEY] = str(a1 + a2)


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

        for item in items:
            if not isinstance(item, dict):
                continue
            apply_form2_final_amount_row(item, form_type)

    return page_results
