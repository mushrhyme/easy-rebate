"""
스키마 검증 스크립트

외래키 제약조건, 인덱스, 테이블 구조를 확인합니다.
"""
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.registry import get_db
from psycopg2.extras import RealDictCursor


def check_foreign_keys(db):
    """외래키 제약조건 확인"""
    print("=" * 80)
    print("외래키 제약조건 확인")
    print("=" * 80)
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                rc.delete_rule
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            LEFT JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            LEFT JOIN information_schema.referential_constraints AS rc
                ON rc.constraint_name = tc.constraint_name
                AND rc.constraint_schema = tc.table_schema
            WHERE tc.table_schema = 'public'
                AND tc.table_name IN (
                    'page_data_current', 'page_data_archive',
                    'items_current', 'items_archive',
                    'page_images_current', 'page_images_archive',
                    'item_locks_current', 'item_locks_archive',
                    'rag_learning_status_current', 'rag_learning_status_archive'
                )
                AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_name, tc.constraint_name;
        """)
        
        results = cursor.fetchall()
        
        if not results:
            print("⚠️ 외래키 제약조건이 없습니다!")
            return False
        
        print(f"\n✅ 총 {len(results)}개의 외래키 제약조건 발견:\n")
        
        issues = []
        for row in results:
            table_name = row['table_name']
            constraint_name = row['constraint_name']
            column_name = row['column_name']
            foreign_table = row['foreign_table_name']
            foreign_column = row['foreign_column_name']
            delete_rule = row['delete_rule']
            
            # 올바른 참조인지 확인
            is_correct = False
            if table_name.endswith('_current'):
                expected_table = foreign_table.replace('_archive', '_current')
                if foreign_table == expected_table or foreign_table.endswith('_current'):
                    is_correct = True
            elif table_name.endswith('_archive'):
                expected_table = foreign_table.replace('_current', '_archive')
                if foreign_table == expected_table or foreign_table.endswith('_archive'):
                    is_correct = True
            
            status = "✅" if is_correct else "❌"
            print(f"{status} {table_name}.{column_name} → {foreign_table}.{foreign_column} ({delete_rule})")
            
            if not is_correct:
                issues.append({
                    'table': table_name,
                    'column': column_name,
                    'references': f"{foreign_table}.{foreign_column}",
                    'expected': f"{expected_table}.{foreign_column}" if 'expected_table' in locals() else "N/A"
                })
        
        if issues:
            print(f"\n❌ 문제 발견: {len(issues)}개의 잘못된 외래키")
            for issue in issues:
                print(f"   - {issue['table']}.{issue['column']}: {issue['references']} (예상: {issue['expected']})")
            return False
        else:
            print("\n✅ 모든 외래키 제약조건이 올바릅니다!")
            return True


def check_indexes(db):
    """인덱스 확인 (중복 및 불필요한 인덱스)"""
    print("\n" + "=" * 80)
    print("인덱스 확인 (중복 및 불필요한 인덱스)")
    print("=" * 80)
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # PRIMARY KEY와 UNIQUE 제약조건으로 자동 생성된 인덱스 확인
        cursor.execute("""
            SELECT 
                t.relname AS table_name,
                i.relname AS index_name,
                a.attname AS column_name,
                ix.indisprimary AS is_primary,
                ix.indisunique AS is_unique
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE t.relkind = 'r'
                AND t.relname IN (
                    'item_locks_current', 'item_locks_archive'
                )
                AND i.relname LIKE '%item_id%'
            ORDER BY t.relname, i.relname;
        """)
        
        results = cursor.fetchall()
        
        if not results:
            print("✅ item_id 관련 인덱스 문제 없음")
            return True
        
        print(f"\n발견된 item_id 관련 인덱스:\n")
        
        issues = []
        for row in results:
            table_name = row['table_name']
            index_name = row['index_name']
            column_name = row['column_name']
            is_primary = row['is_primary']
            is_unique = row['is_unique']
            
            # PRIMARY KEY가 아닌데 item_id 인덱스가 있으면 불필요
            if not is_primary and 'item_id' in index_name.lower():
                status = "❌"
                issues.append({
                    'table': table_name,
                    'index': index_name,
                    'reason': 'PRIMARY KEY가 이미 인덱스를 제공하므로 불필요'
                })
            else:
                status = "✅"
            
            pk_str = " (PRIMARY KEY)" if is_primary else ""
            unique_str = " (UNIQUE)" if is_unique and not is_primary else ""
            print(f"{status} {table_name}.{index_name} on {column_name}{pk_str}{unique_str}")
        
        if issues:
            print(f"\n❌ 불필요한 인덱스 발견: {len(issues)}개")
            for issue in issues:
                print(f"   - {issue['table']}.{issue['index']}: {issue['reason']}")
            return False
        else:
            print("\n✅ 모든 인덱스가 적절합니다!")
            return True


def check_table_structure(db):
    """테이블 구조 확인 (컬럼 중복 등)"""
    print("\n" + "=" * 80)
    print("테이블 구조 확인")
    print("=" * 80)
    
    tables = [
        'documents_current', 'documents_archive',
        'page_data_current', 'page_data_archive',
        'items_current', 'items_archive',
        'page_images_current', 'page_images_archive',
        'item_locks_current', 'item_locks_archive',
        'rag_learning_status_current', 'rag_learning_status_archive',
        'rag_vector_index',
        'users', 'user_sessions'
    ]
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        all_ok = True
        for table_name in tables:
            cursor.execute("""
                SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                    AND table_name = %s
                ORDER BY ordinal_position;
            """, (table_name,))
            
            columns = cursor.fetchall()
            
            if not columns:
                print(f"⚠️ 테이블 '{table_name}'이 존재하지 않습니다.")
                all_ok = False
                continue
            
            # 컬럼명 중복 확인
            column_names = [col['column_name'] for col in columns]
            duplicates = [name for name in column_names if column_names.count(name) > 1]
            
            if duplicates:
                print(f"❌ {table_name}: 중복된 컬럼명 발견 - {duplicates}")
                all_ok = False
            else:
                print(f"✅ {table_name}: {len(columns)}개 컬럼 (정상)")
        
        if all_ok:
            print("\n✅ 모든 테이블 구조가 정상입니다!")
        
        return all_ok


def check_primary_keys(db):
    """PRIMARY KEY 확인"""
    print("\n" + "=" * 80)
    print("PRIMARY KEY 확인")
    print("=" * 80)
    
    tables = [
        'documents_current', 'documents_archive',
        'page_data_current', 'page_data_archive',
        'items_current', 'items_archive',
        'page_images_current', 'page_images_archive',
        'item_locks_current', 'item_locks_archive',
        'rag_learning_status_current', 'rag_learning_status_archive',
        'rag_vector_index',
        'users', 'user_sessions'
    ]
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        all_ok = True
        for table_name in tables:
            cursor.execute("""
                SELECT 
                    tc.constraint_name,
                    kcu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                    AND tc.table_name = %s
                    AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position;
            """, (table_name,))
            
            pk_columns = cursor.fetchall()
            
            if not pk_columns:
                print(f"⚠️ {table_name}: PRIMARY KEY가 없습니다.")
                all_ok = False
            else:
                pk_cols = [col['column_name'] for col in pk_columns]
                print(f"✅ {table_name}: PRIMARY KEY ({', '.join(pk_cols)})")
        
        if all_ok:
            print("\n✅ 모든 테이블에 PRIMARY KEY가 정상적으로 설정되어 있습니다!")
        
        return all_ok


def main():
    """메인 함수"""
    print("🔍 데이터베이스 스키마 검증 시작\n")
    
    try:
        db = get_db()
        
        results = {
            'foreign_keys': check_foreign_keys(db),
            'indexes': check_indexes(db),
            'table_structure': check_table_structure(db),
            'primary_keys': check_primary_keys(db)
        }
        
        print("\n" + "=" * 80)
        print("검증 결과 요약")
        print("=" * 80)
        
        all_passed = all(results.values())
        
        for check_name, passed in results.items():
            status = "✅ 통과" if passed else "❌ 실패"
            print(f"{check_name}: {status}")
        
        if all_passed:
            print("\n🎉 모든 검증을 통과했습니다!")
            return 0
        else:
            print("\n⚠️ 일부 검증에 실패했습니다. 위의 상세 내용을 확인하세요.")
            return 1
            
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
