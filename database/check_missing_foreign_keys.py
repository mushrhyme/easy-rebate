"""
누락된 외래키 확인 스크립트
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.registry import get_db
from psycopg2.extras import RealDictCursor


def check_specific_foreign_keys(db):
    """특정 테이블의 외래키 확인"""
    print("=" * 80)
    print("특정 테이블 외래키 확인")
    print("=" * 80)
    
    # 확인할 테이블과 예상되는 외래키
    expected_fks = {
        'page_images_current': {
            'pdf_filename': 'documents_current.pdf_filename'
        },
        'page_images_archive': {
            'pdf_filename': 'documents_archive.pdf_filename'
        },
        'item_locks_current': {
            'item_id': 'items_current.item_id'
        },
        'item_locks_archive': {
            'item_id': 'items_archive.item_id'
        }
    }
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        all_ok = True
        
        for table_name, expected in expected_fks.items():
            print(f"\n📋 {table_name} 테이블 확인:")
            
            # 실제 외래키 확인
            cursor.execute("""
                SELECT 
                    tc.constraint_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                LEFT JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                    AND tc.table_name = %s
                    AND tc.constraint_type = 'FOREIGN KEY';
            """, (table_name,))
            
            actual_fks = cursor.fetchall()
            
            for column, expected_ref in expected.items():
                found = False
                for fk in actual_fks:
                    if fk['column_name'] == column:
                        expected_table, expected_col = expected_ref.split('.')
                        if (fk['foreign_table_name'] == expected_table and 
                            fk['foreign_column_name'] == expected_col):
                            print(f"  ✅ {column} → {fk['foreign_table_name']}.{fk['foreign_column_name']}")
                            found = True
                            break
                        else:
                            print(f"  ⚠️ {column} → {fk['foreign_table_name']}.{fk['foreign_column_name']} (예상: {expected_ref})")
                            found = True
                            break
                
                if not found:
                    print(f"  ❌ {column} → {expected_ref} (외래키 없음)")
                    all_ok = False
        
        return all_ok


def main():
    print("🔍 누락된 외래키 확인\n")
    
    try:
        db = get_db()
        result = check_specific_foreign_keys(db)
        
        print("\n" + "=" * 80)
        if result:
            print("✅ 모든 외래키가 올바르게 설정되어 있습니다!")
        else:
            print("❌ 일부 외래키가 누락되었거나 잘못 설정되어 있습니다.")
            print("   migrate_fix_foreign_keys.sql 스크립트를 다시 실행하세요.")
        
        return 0 if result else 1
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
