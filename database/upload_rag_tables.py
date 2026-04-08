"""
내려받은 rag_page_embeddings, rag_vector_index JSON을 DB에 적재합니다.
기존 두 테이블 내용을 삭제한 뒤, 지정 디렉터리의 JSON에서 읽어 업로드합니다.

실행: python -m database.upload_rag_tables
      python -m database.upload_rag_tables --from-dir ./my_export
테이블 없음 오류 시: psql ... -f database/migrate_rag_pgvector.sql
  (또는 이 스크립트가 시작 시 rag_page_embeddings를 자동 생성)
"""

import argparse
import base64
import json
import sys
from pathlib import Path

# 프로젝트 루트 기준 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.registry import get_db


def ensure_rag_pgvector_schema(db) -> None:
    """
    예전 init_database로만 만든 DB에는 rag_page_embeddings / vector 확장이 없을 수 있음.
    Git 최신 스키마와 동일하게 idempotent 생성 (upload 전 1회 호출).
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as e:
            err = str(e).lower()
            if "vector" in err or "extension" in err:
                raise RuntimeError(
                    "PostgreSQL에 pgvector 확장을 로드할 수 없습니다. "
                    "서버에 pgvector를 설치한 뒤 다시 시도하세요 "
                    "(예: macOS+brew: brew install pgvector, PostgreSQL 버전과 맞춤). "
                    f"원본 오류: {e}"
                ) from e
            raise
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_page_embeddings (
                id SERIAL PRIMARY KEY,
                pdf_filename VARCHAR(500) NOT NULL,
                page_number INTEGER NOT NULL,
                ocr_text TEXT NOT NULL,
                embedding vector(384) NOT NULL,
                answer_json JSON NOT NULL,
                form_type VARCHAR(10),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pdf_filename, page_number)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_page_embeddings_form_type "
            "ON rag_page_embeddings(form_type)"
        )
        cursor.execute(
            """
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'rag_page_embeddings'
              AND indexname = 'idx_rag_page_embeddings_hnsw'
            """
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_page_embeddings_hnsw
                ON rag_page_embeddings USING hnsw (embedding vector_cosine_ops)
                """
            )
        conn.commit()


def _list_to_vector_str(arr: list) -> str:
    """float 리스트 → pgvector 리터럴 문자열. (예: [0.1,0.2] → '[0.1,0.2]')"""
    if not arr:
        return "[]"
    return "[" + ",".join(str(float(x)) for x in arr) + "]"


def load_embeddings(path: Path) -> list:
    """rag_page_embeddings.json 로드."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_vector_index(path: Path) -> list:
    """rag_vector_index.json 로드."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def upload_rag_page_embeddings(db, rows: list) -> int:
    """rag_page_embeddings 비우고 JSON 행들 INSERT. 반환: 삽입 행 수."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE rag_page_embeddings RESTART IDENTITY")
        count = 0
        for r in rows:
            emb = r.get("embedding") or []
            vec_str = _list_to_vector_str(emb)
            answer_json = r.get("answer_json")
            if isinstance(answer_json, (dict, list)):
                answer_json = json.dumps(answer_json, ensure_ascii=False)
            # updated_at 없으면 CURRENT_TIMESTAMP 사용
            cursor.execute("""
                INSERT INTO rag_page_embeddings (pdf_filename, page_number, ocr_text, embedding, answer_json, form_type, updated_at)
                VALUES (%s, %s, %s, %s::vector, %s::json, %s, COALESCE(NULLIF(%s, '')::timestamptz, CURRENT_TIMESTAMP))
            """, (
                r.get("pdf_filename"),
                r.get("page_number"),
                r.get("ocr_text") or "",
                vec_str,
                answer_json or "{}",
                r.get("form_type"),
                r.get("updated_at") or "",
            ))
            count += 1
        conn.commit()
    return count


def upload_rag_vector_index(db, rows: list) -> int:
    """rag_vector_index 비우고 JSON 행들 INSERT. 반환: 삽입 행 수."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE rag_vector_index RESTART IDENTITY")
        count = 0
        for r in rows:
            b64 = r.get("index_data_b64") or ""
            raw = base64.b64decode(b64) if b64 else b""
            meta = r.get("metadata_json")
            if isinstance(meta, (dict, list)):
                meta = json.dumps(meta, ensure_ascii=False)
            cursor.execute("""
                INSERT INTO rag_vector_index (index_name, form_type, index_data, metadata_json, index_size, vector_count)
                VALUES (%s, %s, %s, %s::json, %s, %s)
            """, (
                r.get("index_name"),
                r.get("form_type"),
                raw,
                meta or "{}",
                r.get("index_size"),
                r.get("vector_count"),
            ))
            count += 1
        conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="내려받은 RAG 테이블 데이터 업로드 (기존 내용 삭제 후 적재)")
    parser.add_argument("--from-dir", type=str, default=None,
                        help="내려받은 JSON이 있는 디렉터리 (기본: database/rag_export 중 최신)")
    args = parser.parse_args()

    from_dir = Path(args.from_dir).resolve() if args.from_dir else None
    if from_dir is None:
        base = Path(__file__).resolve().parent / "rag_export"
        if not base.exists():
            print(f"rag_export 폴더가 없습니다. 먼저 download_rag_tables.py를 실행하세요.")
            sys.exit(1)
        subdirs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda p: p.name, reverse=True)
        if not subdirs:
            print("rag_export 안에 하위 디렉터리가 없습니다.")
            sys.exit(1)
        from_dir = subdirs[0]
        print(f"Using latest export: {from_dir}")

    path_emb = from_dir / "rag_page_embeddings.json"
    path_idx = from_dir / "rag_vector_index.json"
    if not path_emb.exists():
        print(f"파일 없음: {path_emb}")
        sys.exit(1)
    if not path_idx.exists():
        print(f"파일 없음: {path_idx}")
        sys.exit(1)

    db = get_db()
    ensure_rag_pgvector_schema(db)

    # 1) rag_page_embeddings
    print("Loading rag_page_embeddings.json...")
    embeddings = load_embeddings(path_emb)
    print(f"  Truncate + Insert {len(embeddings)} rows...")
    n_emb = upload_rag_page_embeddings(db, embeddings)
    print(f"  -> {n_emb} rows uploaded.")

    # 2) rag_vector_index
    print("Loading rag_vector_index.json...")
    vector_index = load_vector_index(path_idx)
    print(f"  Truncate + Insert {len(vector_index)} rows...")
    n_idx = upload_rag_vector_index(db, vector_index)
    print(f"  -> {n_idx} rows uploaded.")

    print("\nDone.")


if __name__ == "__main__":
    main()
