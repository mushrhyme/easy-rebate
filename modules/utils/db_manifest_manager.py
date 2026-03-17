"""
DB 기반 Manifest 관리 모듈

rag_page_embeddings(pgvector)를 기준으로 벡터 DB 등록 페이지를 추적합니다.
(기존 rag_learning_status_* 테이블 제거 후 pgvector 단일 소스 사용)
"""

from typing import Dict, Set, Optional, List, Any
from database.registry import get_db
import psycopg2
import psycopg2.errors


class DBManifestManager:
    """
    rag_page_embeddings 기준 Manifest 관리.
    등록 여부 = rag_page_embeddings에 행 존재 여부.
    """

    def __init__(self):
        self.db = get_db()

    def _table_exists(self) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'rag_page_embeddings')
                """)
                return bool(cursor.fetchone()[0])
        except Exception:
            return False

    def get_page_info(self, pdf_filename: str, page_number: int) -> Optional[Dict[str, Any]]:
        """rag_page_embeddings에 있으면 merged 상태 정보 반환."""
        if not self._table_exists():
            return None
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, pdf_filename, page_number, updated_at
                    FROM rag_page_embeddings
                    WHERE pdf_filename = %s AND page_number = %s
                """, (pdf_filename, page_number))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    'learning_id': row[0],
                    'pdf_filename': row[1],
                    'page_number': row[2],
                    'status': 'merged',
                    'page_hash': None,
                    'fingerprint_mtime': None,
                    'fingerprint_size': None,
                    'shard_id': None,
                    'created_at': None,
                    'updated_at': row[3]
                }
        except Exception:
            return None

    def get_page_status(self, pdf_filename: str, page_number: int) -> Optional[str]:
        """등록되어 있으면 'merged', 없으면 None."""
        info = self.get_page_info(pdf_filename, page_number)
        return info.get('status') if info else None

    def is_processed(self, pdf_filename: str, page_number: int, page_hash: str) -> bool:
        """rag_page_embeddings에 존재하면 처리됨으로 간주 (hash는 미비교)."""
        return self.get_page_info(pdf_filename, page_number) is not None

    def is_staged(self, pdf_filename: str, page_number: int) -> bool:
        """pgvector에는 staged 개념 없음 → 항상 False."""
        return False

    def is_file_changed_fast(
        self,
        pdf_filename: str,
        page_number: int,
        fingerprint: Dict[str, Any]
    ) -> bool:
        """등록되지 않은 페이지면 True(변경됨). 등록된 페이지는 fingerprint 없어 False 반환."""
        return self.get_page_info(pdf_filename, page_number) is None

    def mark_pages_staged(
        self,
        pages: List[Dict[str, Any]],
        shard_id: str,
        page_hashes: Dict[str, str],
        fingerprints: Dict[str, Dict[str, Any]]
    ) -> None:
        """pgvector에는 staged 없음 → no-op."""
        pass

    def mark_pages_merged(self, pages: List[Dict[str, Any]]) -> None:
        """pgvector는 build_pgvector_db/학습 요청으로 갱신 → no-op."""
        pass

    def mark_pages_deleted(self, pages: List[Dict[str, Any]]) -> None:
        """rag_page_embeddings에서 해당 (pdf_filename, page_number) 삭제."""
        if not pages or not self._table_exists():
            return
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                for page_info in pages:
                    cursor.execute("""
                        DELETE FROM rag_page_embeddings
                        WHERE pdf_filename = %s AND page_number = %s
                    """, (page_info['pdf_filename'], page_info['page_number']))
                conn.commit()
        except Exception as e:
            print(f"⚠️ mark_pages_deleted 오류: {e}")

    def get_all_page_keys(self) -> Set[str]:
        """rag_page_embeddings에 등록된 모든 (pdf, page)의 page_key 집합."""
        from modules.utils.hash_utils import get_page_key
        try:
            if not self._table_exists():
                return set()
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT pdf_filename, page_number FROM rag_page_embeddings")
                page_keys = set()
                for row in cursor.fetchall():
                    pdf_name = (row[0] or "").replace('.pdf', '')
                    page_key = get_page_key(pdf_name, row[1])
                    page_keys.add(page_key)
                return page_keys
        except psycopg2.errors.UndefinedTable:
            return set()

    def get_staged_page_keys(self) -> Set[str]:
        """pgvector에는 staged 없음 → 빈 집합."""
        return set()

    def get_deleted_page_keys(self) -> Set[str]:
        """pgvector에는 deleted 추적 없음 → 빈 집합."""
        return set()
