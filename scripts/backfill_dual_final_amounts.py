"""
기존 item_data 백필:
- 01~05 유형의 조건2/금액2 누락 시 null 보정
- 최종금액(최종請求金額/최종請求額) 재계산

사용:
  python scripts/backfill_dual_final_amounts.py
"""

import json
from typing import Any, Dict, Iterable, Tuple

from database.registry import get_db
from modules.utils.form2_rebate_utils import apply_form2_final_amount_row


def _load_rows(conn, table_name: str) -> Iterable[Tuple[int, str, Dict[str, Any], str]]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT i.item_id, i.pdf_filename, i.item_data::text, COALESCE(d.form_type, '')
            FROM {table_name} i
            LEFT JOIN documents_current d ON d.pdf_filename = i.pdf_filename
            ORDER BY i.item_id
            """
        )
        for item_id, pdf_filename, item_data_text, form_type in cursor.fetchall():
            try:
                item_data = json.loads(item_data_text) if item_data_text else {}
            except Exception:
                item_data = {}
            if not isinstance(item_data, dict):
                item_data = {}
            yield item_id, pdf_filename, item_data, str(form_type or "").strip()


def _update_row(conn, table_name: str, item_id: int, item_data: Dict[str, Any]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table_name} SET item_data = %s::json WHERE item_id = %s",
            (json.dumps(item_data, ensure_ascii=False), item_id),
        )


def _normalize_table(conn, table_name: str) -> Tuple[int, int]:
    checked = 0
    changed = 0
    for item_id, _pdf, item_data, form_type in _load_rows(conn, table_name):
        checked += 1
        before = json.dumps(item_data, ensure_ascii=False, sort_keys=True)
        apply_form2_final_amount_row(item_data, form_type)  # 01~05 공통 적용
        after = json.dumps(item_data, ensure_ascii=False, sort_keys=True)
        if before != after:
            _update_row(conn, table_name, item_id, item_data)
            changed += 1
    return checked, changed


def main() -> None:
    db = get_db()
    with db.get_connection() as conn:
        cur_checked, cur_changed = _normalize_table(conn, "items_current")
        arc_checked, arc_changed = _normalize_table(conn, "items_archive")
        conn.commit()

    print(
        "[backfill_dual_final_amounts] done",
        f"items_current: checked={cur_checked}, changed={cur_changed}",
        f"items_archive: checked={arc_checked}, changed={arc_changed}",
    )


if __name__ == "__main__":
    main()

