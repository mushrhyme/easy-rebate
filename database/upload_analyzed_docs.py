"""
내려받은 분석 완료 문서(8개 테이블) JSON을 DB에 적재합니다.
기존 current/archive 내용을 삭제한 뒤, 지정 디렉터리의 JSON에서 읽어 업로드합니다.

실행: python -m database.upload_analyzed_docs
      python -m database.upload_analyzed_docs --from-dir ./my_docs_export
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg2.extras import Json
from database.registry import get_db

# 테이블별 PK 컬럼 (INSERT 시 제외, SERIAL로 자동 생성)
TABLE_PK = {
    "documents_current": "document_id",
    "documents_archive": "document_id",
    "page_data_current": "page_data_id",
    "page_data_archive": "page_data_id",
    "items_current": "item_id",
    "items_archive": "item_id",
    "page_images_current": "image_id",
    "page_images_archive": "image_id",
}

# TRUNCATE 순서 (FK: items → page_data, page_images → documents)
TRUNCATE_ORDER = [
    "items_current",
    "items_archive",
    "page_data_current",
    "page_data_archive",
    "page_images_current",
    "page_images_archive",
    "documents_current",
    "documents_archive",
]

# INSERT 순서 (documents 먼저, 그 다음 page_data/page_images, 마지막 items)
INSERT_ORDER = [
    "documents_current",
    "documents_archive",
    "page_data_current",
    "page_data_archive",
    "page_images_current",
    "page_images_archive",
    "items_current",
    "items_archive",
]


def _serialize_val(v):
    """JSON에서 읽은 값을 DB 파라미터로. dict/list → Json 어댑터."""
    if isinstance(v, (dict, list)):
        return Json(v)
    return v


def load_table_json(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def truncate_all(db):
    with db.get_connection() as conn:
        cur = conn.cursor()
        for table in TRUNCATE_ORDER:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        conn.commit()


def insert_table(db, table: str, rows: list) -> int:
    if not rows:
        return 0
    pk_col = TABLE_PK[table]
    # 첫 행 기준 컬럼 목록 (PK 제외)
    cols = [k for k in rows[0].keys() if k != pk_col]
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"

    with db.get_connection() as conn:
        cur = conn.cursor()
        for r in rows:
            vals = [_serialize_val(r.get(c)) for c in cols]
            cur.execute(sql, vals)
        conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="내려받은 분석 완료 문서 업로드 (기존 삭제 후 적재)")
    parser.add_argument("--from-dir", type=str, default=None,
                        help="내려받은 JSON 디렉터리 (기본: database/analyzed_docs_export 중 최신)")
    args = parser.parse_args()

    from_dir = Path(args.from_dir).resolve() if args.from_dir else None
    if from_dir is None:
        base = Path(__file__).resolve().parent / "analyzed_docs_export"
        if not base.exists():
            print("analyzed_docs_export 폴더가 없습니다. 먼저 download_analyzed_docs.py를 실행하세요.")
            sys.exit(1)
        subdirs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda p: p.name, reverse=True)
        if not subdirs:
            print("analyzed_docs_export 안에 하위 디렉터리가 없습니다.")
            sys.exit(1)
        from_dir = subdirs[0]
        print(f"Using latest export: {from_dir}")

    for table in INSERT_ORDER:
        if not (from_dir / f"{table}.json").exists():
            print(f"파일 없음: {from_dir / f'{table}.json'}")
            sys.exit(1)

    db = get_db()

    print("Truncating tables (FK order)...")
    truncate_all(db)
    print("  Done.")

    for table in INSERT_ORDER:
        path = from_dir / f"{table}.json"
        print(f"Loading {path.name}...")
        rows = load_table_json(path)
        n = insert_table(db, table, rows)
        print(f"  -> {n} rows uploaded.")

    print("\nDone.")


if __name__ == "__main__":
    main()
