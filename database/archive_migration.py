"""
아카이브 마이그레이션 스크립트

매월 1일 0시에 실행되어 이전 달 데이터를 
현재연월용 테이블에서 아카이브용 테이블로 이동시킵니다.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.registry import get_db


class ArchiveMigration:
    """아카이브 마이그레이션 클래스"""
    
    def __init__(self, db=None):
        """
        초기화
        
        Args:
            db: DatabaseManager 인스턴스 (None이면 자동 생성)
        """
        self.db = db or get_db()
    
    def get_previous_month(self) -> Tuple[int, int]:
        """
        이전 달의 연월 반환
        
        Returns:
            (year, month) 튜플
        """
        now = datetime.now()
        # 이전 달 계산
        if now.month == 1:
            prev_year = now.year - 1
            prev_month = 12
        else:
            prev_year = now.year
            prev_month = now.month - 1
        
        return (prev_year, prev_month)
    
    def migrate_documents(self, year: int, month: int) -> int:
        """
        documents_current에서 documents_archive로 이동
        
        Args:
            year: 이동할 연도
            month: 이동할 월
            
        Returns:
            이동된 문서 수
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 이전 달 데이터 조회 및 이동
                cursor.execute("""
                    INSERT INTO documents_archive
                    SELECT * FROM documents_current
                    WHERE data_year = %s AND data_month = %s
                    ON CONFLICT (pdf_filename) DO UPDATE SET
                        total_pages = EXCLUDED.total_pages,
                        form_type = EXCLUDED.form_type,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                """, (year, month))
                
                moved_count = cursor.rowcount
                
                # 이동된 문서의 pdf_filename 목록 가져오기
                cursor.execute("""
                    SELECT pdf_filename 
                    FROM documents_archive
                    WHERE data_year = %s AND data_month = %s
                """, (year, month))
                
                moved_filenames = [row[0] for row in cursor.fetchall()]
                
                # documents_current에서 삭제
                if moved_filenames:
                    placeholders = ','.join(['%s'] * len(moved_filenames))
                    cursor.execute(f"""
                        DELETE FROM documents_current
                        WHERE pdf_filename IN ({placeholders})
                    """, moved_filenames)
                
                conn.commit()
                return moved_count
                
        except Exception as e:
            print(f"❌ documents 마이그레이션 실패: {e}")
            raise
    
    def migrate_related_data(self, pdf_filenames: List[str], table_pairs: List[Tuple[str, str]]):
        """
        관련 테이블 데이터 이동
        
        Args:
            pdf_filenames: 이동할 문서의 pdf_filename 목록
            table_pairs: (current_table, archive_table) 튜플 리스트
        """
        if not pdf_filenames:
            return
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                placeholders = ','.join(['%s'] * len(pdf_filenames))
                
                for current_table, archive_table in table_pairs:
                    if 'item_locks' in current_table:
                        # item_locks는 item_id로 조인 필요
                        cursor.execute(f"""
                            INSERT INTO {archive_table}
                            SELECT ilc.*
                            FROM {current_table} ilc
                            INNER JOIN items_current ic ON ilc.item_id = ic.item_id
                            WHERE ic.pdf_filename IN ({placeholders})
                            ON CONFLICT (item_id) DO NOTHING
                        """, pdf_filenames)
                        
                        # 삭제
                        cursor.execute(f"""
                            DELETE FROM {current_table}
                            WHERE item_id IN (
                                SELECT item_id FROM items_current
                                WHERE pdf_filename IN ({placeholders})
                            )
                        """, pdf_filenames + pdf_filenames)
                    else:
                        # 일반 테이블 (pdf_filename 직접 사용)
                        # UNIQUE 제약조건이 있는 경우 ON CONFLICT 사용
                        if 'page_data' in current_table:
                            # page_data는 (pdf_filename, page_number) UNIQUE
                            cursor.execute(f"""
                                INSERT INTO {archive_table}
                                SELECT * FROM {current_table}
                                WHERE pdf_filename IN ({placeholders})
                                ON CONFLICT (pdf_filename, page_number) DO NOTHING
                            """, pdf_filenames)
                        elif 'page_images' in current_table:
                            # page_images는 (pdf_filename, page_number) UNIQUE
                            cursor.execute(f"""
                                INSERT INTO {archive_table}
                                SELECT * FROM {current_table}
                                WHERE pdf_filename IN ({placeholders})
                                ON CONFLICT (pdf_filename, page_number) DO NOTHING
                            """, pdf_filenames)
                        elif 'items' in current_table:
                            # items는 item_id가 PRIMARY KEY이므로 ON CONFLICT 사용
                            cursor.execute(f"""
                                INSERT INTO {archive_table}
                                SELECT * FROM {current_table}
                                WHERE pdf_filename IN ({placeholders})
                                ON CONFLICT (item_id) DO NOTHING
                            """, pdf_filenames)
                        else:
                            # 기타 테이블
                            cursor.execute(f"""
                                INSERT INTO {archive_table}
                                SELECT * FROM {current_table}
                                WHERE pdf_filename IN ({placeholders})
                            """, pdf_filenames)
                        
                        # 삭제
                        cursor.execute(f"""
                            DELETE FROM {current_table}
                            WHERE pdf_filename IN ({placeholders})
                        """, pdf_filenames)
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ 관련 데이터 마이그레이션 실패: {e}")
            raise
    
    def cleanup_old_archive(self, retention_years: int = 1):
        """
        1년 이상 된 아카이브 데이터 삭제
        
        Args:
            retention_years: 보관 기간 (년)
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_years * 365)
            cutoff_year = cutoff_date.year
            cutoff_month = cutoff_date.month
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 1년 이상 된 데이터의 pdf_filename 조회
                cursor.execute("""
                    SELECT pdf_filename
                    FROM documents_archive
                    WHERE (data_year < %s) OR (data_year = %s AND data_month < %s)
                """, (cutoff_year, cutoff_year, cutoff_month))
                
                old_filenames = [row[0] for row in cursor.fetchall()]
                
                if not old_filenames:
                    print(f"✅ 삭제할 오래된 데이터 없음")
                    return 0
                
                print(f"🗑️  {len(old_filenames)}개 문서의 오래된 데이터 삭제 중...")
                
                # 관련 테이블에서 삭제
                placeholders = ','.join(['%s'] * len(old_filenames))
                
                tables_to_clean = [
                    'items_archive',
                    'page_data_archive',
                    'page_images_archive',
                    'item_locks_archive'
                ]
                
                for table in tables_to_clean:
                    if 'item_locks' in table:
                        cursor.execute(f"""
                            DELETE FROM {table}
                            WHERE item_id IN (
                                SELECT item_id FROM items_archive
                                WHERE pdf_filename IN ({placeholders})
                            )
                        """, old_filenames)
                    else:
                        cursor.execute(f"""
                            DELETE FROM {table}
                            WHERE pdf_filename IN ({placeholders})
                        """, old_filenames)
                
                # documents_archive에서 삭제
                cursor.execute(f"""
                    DELETE FROM documents_archive
                    WHERE pdf_filename IN ({placeholders})
                """, old_filenames)
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                print(f"✅ {deleted_count}개 문서의 오래된 데이터 삭제 완료")
                return deleted_count
                
        except Exception as e:
            print(f"❌ 오래된 데이터 삭제 실패: {e}")
            raise
    
    def run_migration(self, target_year: int = None, target_month: int = None):
        """
        마이그레이션 실행
        
        Args:
            target_year: 대상 연도 (None이면 이전 달)
            target_month: 대상 월 (None이면 이전 달)
        """
        if target_year is None or target_month is None:
            target_year, target_month = self.get_previous_month()
        
        print(f"🔄 아카이브 마이그레이션 시작: {target_year}년 {target_month}월")
        
        try:
            # 1. documents 이동
            moved_count = self.migrate_documents(target_year, target_month)
            print(f"✅ {moved_count}개 문서 이동 완료")
            
            if moved_count == 0:
                print("⚠️  이동할 데이터가 없습니다.")
                return
            
            # 2. 이동된 문서의 pdf_filename 목록 가져오기
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT pdf_filename 
                    FROM documents_archive
                    WHERE data_year = %s AND data_month = %s
                """, (target_year, target_month))
                moved_filenames = [row[0] for row in cursor.fetchall()]
            
            # 3. 관련 테이블 이동
            table_pairs = [
                ('page_data_current', 'page_data_archive'),
                ('items_current', 'items_archive'),
                ('page_images_current', 'page_images_archive'),
                ('item_locks_current', 'item_locks_archive'),
            ]
            
            self.migrate_related_data(moved_filenames, table_pairs)
            print(f"✅ 관련 테이블 데이터 이동 완료")
            
            # 4. 1년 이상 된 데이터 삭제
            self.cleanup_old_archive(retention_years=1)
            
            print(f"✅ 아카이브 마이그레이션 완료: {target_year}년 {target_month}월")
            
        except Exception as e:
            print(f"❌ 마이그레이션 실패: {e}")
            raise


def main():
    """메인 함수 (스크립트 직접 실행 시)"""
    migration = ArchiveMigration()
    
    # 명령줄 인자로 연월 지정 가능
    if len(sys.argv) >= 3:
        target_year = int(sys.argv[1])
        target_month = int(sys.argv[2])
        migration.run_migration(target_year, target_month)
    else:
        # 이전 달 자동 마이그레이션
        migration.run_migration()


if __name__ == "__main__":
    main()
