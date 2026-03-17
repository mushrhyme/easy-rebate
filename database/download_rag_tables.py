"""
rag_page_embeddings, rag_vector_index 테이블을 JSON 파일로 내려받습니다.
.env에 설정된 DB에서 읽어 database/rag_export/<timestamp>/ 에 저장합니다.

실행: python -m database.download_rag_tables
      python -m database.download_rag_tables --out-dir ./my_export
"""

import argparse
import base64
import json
import sys
from pathlib import Path

# 프로젝트 루트 기준 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.registry import get_db


def _embedding_to_list(val) -> list:
    """DB vector 컬럼 → JSON용 float 리스트. (예: '[0.1,0.2]' or list → [0.1, 0.2])"""
    if val is None:
        return []
    if isinstance(val, list):
        return [float(x) for x in val]
    s = str(val).strip()
    if not s or s == "[]":
        return []
    if s.startswith("["):
        return [float(x.strip()) for x in s[1:-1].split(",") if x.strip()]
    return []


def download_rag_page_embeddings(db) -> list:
    """rag_page_embeddings 전체 행 반환. embedding은 float 리스트로."""
    rows = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pdf_filename, page_number, ocr_text, embedding, answer_json, form_type, updated_at
            FROM rag_page_embeddings
            ORDER BY pdf_filename, page_number
        """)
        for row in cursor.fetchall():
            rows.append({
                "pdf_filename": row[0],
                "page_number": row[1],
                "ocr_text": row[2] or "",
                "embedding": _embedding_to_list(row[3]),
                "answer_json": row[4] if isinstance(row[4], (dict, list)) else (json.loads(row[4]) if isinstance(row[4], str) else {}),
                "form_type": row[5],
                "updated_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
            })
    return rows


def download_rag_vector_index(db) -> list:
    """rag_vector_index 전체 행 반환. index_data는 base64 문자열로."""
    rows = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT index_name, form_type, index_data, metadata_json, index_size, vector_count
            FROM rag_vector_index
            ORDER BY index_name, form_type
        """)
        for row in cursor.fetchall():
            index_data = row[2]
            b64 = base64.b64encode(index_data).decode("ascii") if index_data else ""
            meta = row[3]
            if isinstance(meta, str):
                meta = json.loads(meta) if meta else {}
            rows.append({
                "index_name": row[0],
                "form_type": row[1],
                "index_data_b64": b64,
                "metadata_json": meta,
                "index_size": row[4],
                "vector_count": row[5],
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description="rag_page_embeddings, rag_vector_index 테이블 내려받기")
    parser.add_argument("--out-dir", type=str, default=None,
                        help="저장 디렉터리 (기본: database/rag_export/YYYYMMDD_HHMMSS)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir is None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(__file__).resolve().parent
        out_dir = base / "rag_export" / ts
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    db = get_db()

    # 1) rag_page_embeddings
    print("Downloading rag_page_embeddings...")
    embeddings = download_rag_page_embeddings(db)
    path_emb = out_dir / "rag_page_embeddings.json"
    with open(path_emb, "w", encoding="utf-8") as f:
        json.dump(embeddings, f, ensure_ascii=False, indent=0)
    print(f"  -> {len(embeddings)} rows -> {path_emb}")

    # 2) rag_vector_index
    print("Downloading rag_vector_index...")
    vector_index = download_rag_vector_index(db)
    path_idx = out_dir / "rag_vector_index.json"
    with open(path_idx, "w", encoding="utf-8") as f:
        json.dump(vector_index, f, ensure_ascii=False, indent=0)
    print(f"  -> {len(vector_index)} rows -> {path_idx}")

    print(f"\nDone. Export dir: {out_dir}")


if __name__ == "__main__":
    main()
