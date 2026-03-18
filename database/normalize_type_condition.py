"""
page_role이 detail인데 タイプ가 null인 경우 DB에서 모두 条件으로 일괄 수정.

대상:
- items_current, items_archive (item_data 내 タイプ)
- rag_page_embeddings (answer_json 내 items[].タイプ)

실행: python -m database.normalize_type_condition [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[1]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from psycopg2.extras import RealDictCursor

from database.registry import get_db


def _is_type_null_or_empty(val) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and not (val or "").strip():
        return True
    return False


def normalize_items_table(conn, table: str, page_table: str, dry_run: bool) -> int:
    """items_current 또는 items_archive에서 detail 페이지의 タイプ null → 条件."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        f"""
        SELECT i.item_id, i.item_data, i.pdf_filename, i.page_number
        FROM {table} i
        INNER JOIN {page_table} p
          ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
        WHERE p.page_role = 'detail'
          AND (
            i.item_data->>'タイプ' IS NULL
            OR trim(COALESCE(i.item_data->>'タイプ', '')) = ''
          )
        """
    )
    rows = cursor.fetchall()
    updated = 0
    for row in rows:
        item_data = row["item_data"]
        if isinstance(item_data, str):
            try:
                item_data = json.loads(item_data)
            except json.JSONDecodeError:
                continue
        if not isinstance(item_data, dict):
            continue
        item_data["タイプ"] = "条件"
        if not dry_run:
            cursor.execute(
                f"UPDATE {table} SET item_data = %s::json WHERE item_id = %s",
                (json.dumps(item_data, ensure_ascii=False), row["item_id"]),
            )
            updated += 1
        else:
            updated += 1
    return updated


def normalize_rag_page_embeddings(conn, dry_run: bool) -> int:
    """rag_page_embeddings의 answer_json 내 page_role=detail이고 items[].タイプ가 null인 경우 条件으로 수정."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        """
        SELECT id, pdf_filename, page_number, answer_json
        FROM rag_page_embeddings
        WHERE answer_json->>'page_role' = 'detail'
          AND answer_json->'items' IS NOT NULL
        """
    )
    rows = cursor.fetchall()
    updated = 0
    for row in rows:
        answer_json = row["answer_json"]
        if isinstance(answer_json, str):
            try:
                answer_json = json.loads(answer_json)
            except json.JSONDecodeError:
                continue
        if not isinstance(answer_json, dict):
            continue
        items = answer_json.get("items")
        if not isinstance(items, list):
            continue
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            if _is_type_null_or_empty(item.get("タイプ")):
                item["タイプ"] = "条件"
                changed = True
        if changed and not dry_run:
            cursor.execute(
                "UPDATE rag_page_embeddings SET answer_json = %s::json, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (json.dumps(answer_json, ensure_ascii=False), row["id"]),
            )
            updated += 1
        elif changed:
            updated += 1
    return updated


def run(dry_run: bool = False) -> dict:
    """전체 정규화 실행. 반환: { items_current: n, items_archive: n, rag_page_embeddings: n }."""
    db = get_db()
    counts = {"items_current": 0, "items_archive": 0, "rag_page_embeddings": 0}
    with db.get_connection() as conn:
        counts["items_current"] = normalize_items_table(
            conn, "items_current", "page_data_current", dry_run
        )
        counts["items_archive"] = normalize_items_table(
            conn, "items_archive", "page_data_archive", dry_run
        )
        counts["rag_page_embeddings"] = normalize_rag_page_embeddings(conn, dry_run)
        if not dry_run and (counts["items_current"] + counts["items_archive"] + counts["rag_page_embeddings"]) > 0:
            conn.commit()
    return counts


def main():
    parser = argparse.ArgumentParser(description="detail 페이지에서 タイプ null → 条件 일괄 수정")
    parser.add_argument("--dry-run", action="store_true", help="실제 UPDATE 없이 대상 개수만 출력")
    args = parser.parse_args()
    mode = " (dry-run)" if args.dry_run else ""
    print(f"normalize_type_condition{mode} 시작 ...")
    counts = run(dry_run=args.dry_run)
    print("items_current (detail 페이지 タイプ null → 条件):", counts["items_current"])
    print("items_archive (detail 페이지 タイプ null → 条件):", counts["items_archive"])
    print("rag_page_embeddings (answer_json.items[].タイプ null → 条件):", counts["rag_page_embeddings"])
    if args.dry_run:
        print("--dry-run 이므로 DB 반영 없음. 적용하려면 옵션 없이 실행.")
    else:
        print("완료.")


if __name__ == "__main__":
    main()
