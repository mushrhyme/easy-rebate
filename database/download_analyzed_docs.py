"""
분석 완료된 문서 데이터를 JSON으로 내려받습니다.

대상 테이블 (current/archive):
- documents_* : 문서 메타 (pdf_filename, form_type, data_year, data_month 등)
- page_data_* : 페이지 메타, ocr_text, analyzed_vector_version, last_analyzed_at, page_meta
- items_*     : 행 단위 파싱 결과 (item_data)
- page_images_*: 페이지 이미지 경로

.env에 설정된 DB에서 읽어 database/analyzed_docs_export/<timestamp>/ 에 저장합니다.

실행: python -m database.download_analyzed_docs
      python -m database.download_analyzed_docs --out-dir ./my_docs_export
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg2.extras import RealDictCursor
from database.registry import get_db


def _row_to_json_serializable(row: dict) -> dict:
    """DB row dict에서 datetime/decimal 등 → JSON 호환 형태."""
    out = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (dict, list)):
            out[k] = v
        else:
            out[k] = v
    return out


def _fetch_table(db, table: str) -> list:
    """테이블 전체 조회 → dict 리스트 (JSON 직렬화 가능)."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} ORDER BY 1")
            rows = cur.fetchall()
    return [_row_to_json_serializable(dict(r)) for r in rows]


def main():
    parser = argparse.ArgumentParser(description="분석 완료 문서(8개 테이블) 내려받기")
    parser.add_argument("--out-dir", type=str, default=None,
                        help="저장 디렉터리 (기본: database/analyzed_docs_export/YYYYMMDD_HHMMSS)")
    args = parser.parse_args()

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(__file__).resolve().parent / "analyzed_docs_export" / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    tables = [
        "documents_current",
        "documents_archive",
        "page_data_current",
        "page_data_archive",
        "items_current",
        "items_archive",
        "page_images_current",
        "page_images_archive",
    ]

    db = get_db()
    for table in tables:
        print(f"Downloading {table}...")
        rows = _fetch_table(db, table)
        path = out_dir / f"{table}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=0)
        print(f"  -> {len(rows)} rows -> {path}")

    print(f"\nDone. Export dir: {out_dir}")


if __name__ == "__main__":
    main()
