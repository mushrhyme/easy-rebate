"""
메타데이터에 저장된 key_order 확인 스크립트
"""
import json
import sys
from typing import Dict, Any, Optional

# 프로젝트 루트를 경로에 추가
from pathlib import Path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from modules.core.rag_manager import get_rag_manager
from database.registry import get_db


def check_key_orders():
    """모든 form_type의 key_order를 확인"""
    print("=" * 80)
    print("메타데이터 key_order 확인")
    print("=" * 80)
    
    rag_manager = get_rag_manager()
    form_types = ['01', '02', '03', '04', '05']
    
    # 메모리 메타데이터 확인
    print("\n[메모리 메타데이터]")
    print("-" * 80)
    if rag_manager.metadata:
        print(f"총 {len(rag_manager.metadata)}개의 문서 메타데이터가 메모리에 로드되어 있습니다.")
        
        # form_type별로 그룹화
        form_type_groups: Dict[str, list] = {}
        for doc_id, data in rag_manager.metadata.items():
            metadata_info = data.get("metadata", {})
            form_type = metadata_info.get("form_type", "unknown")
            if form_type not in form_type_groups:
                form_type_groups[form_type] = []
            form_type_groups[form_type].append({
                "doc_id": doc_id,
                "key_order": data.get("key_order"),
                "metadata": metadata_info
            })
        
        for form_type in form_types:
            print(f"\n📋 Form Type: {form_type}")
            if form_type in form_type_groups:
                for item in form_type_groups[form_type]:
                    key_order = item.get("key_order")
                    if key_order:
                        print(f"  ✅ Doc ID: {item['doc_id'][:8]}...")
                        print(f"     page_keys ({len(key_order.get('page_keys', []))}개):")
                        for i, key in enumerate(key_order.get('page_keys', []), 1):
                            print(f"       {i:2d}. {key}")
                        print(f"     item_keys ({len(key_order.get('item_keys', []))}개):")
                        for i, key in enumerate(key_order.get('item_keys', []), 1):
                            print(f"       {i:2d}. {key}")
                    else:
                        print(f"  ⚠️  Doc ID: {item['doc_id'][:8]}... (key_order 없음)")
            else:
                print(f"  ❌ 해당 form_type의 메타데이터가 없습니다.")
    else:
        print("메모리에 메타데이터가 없습니다.")
    
    # DB에서 확인
    print("\n\n[DB 메타데이터]")
    print("-" * 80)
    
    if rag_manager.use_db:
        db = get_db()
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 모든 form_type에 대해 조회
                for form_type in form_types:
                    print(f"\n📋 Form Type: {form_type}")
                    
                    # base 인덱스 조회
                    cursor.execute("""
                        SELECT index_name, metadata_json, updated_at
                        FROM rag_vector_index
                        WHERE index_name = %s AND form_type = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """, (f'base_{form_type}', form_type))
                    
                    row = cursor.fetchone()
                    if row:
                        index_name, metadata_json, updated_at = row
                        print(f"  ✅ Index: {index_name} (업데이트: {updated_at})")
                        
                        # JSON 파싱
                        if isinstance(metadata_json, str):
                            try:
                                metadata_json = json.loads(metadata_json)
                            except Exception as e:
                                print(f"  ⚠️  JSON 파싱 실패: {e}")
                                continue
                        
                        if isinstance(metadata_json, dict):
                            metadata_dict = metadata_json.get('metadata', {})
                            if metadata_dict:
                                # key_order 찾기
                                found_key_order = False
                                for doc_id, data in metadata_dict.items():
                                    if isinstance(data, dict):
                                        metadata_info = data.get("metadata", {})
                                        actual_form_type = metadata_info.get("form_type")
                                        
                                        # form_type 매칭 확인
                                        if (actual_form_type == form_type or 
                                            str(actual_form_type) == str(form_type) or
                                            (isinstance(actual_form_type, int) and str(actual_form_type).zfill(2) == form_type)):
                                            
                                            key_order = data.get("key_order")
                                            if key_order:
                                                found_key_order = True
                                                print(f"     Doc ID: {doc_id[:8]}...")
                                                print(f"     page_keys ({len(key_order.get('page_keys', []))}개):")
                                                for i, key in enumerate(key_order.get('page_keys', []), 1):
                                                    print(f"       {i:2d}. {key}")
                                                print(f"     item_keys ({len(key_order.get('item_keys', []))}개):")
                                                for i, key in enumerate(key_order.get('item_keys', []), 1):
                                                    print(f"       {i:2d}. {key}")
                                
                                if not found_key_order:
                                    # form_type 매칭 없이 첫 번째 key_order 사용
                                    for doc_id, data in metadata_dict.items():
                                        if isinstance(data, dict):
                                            key_order = data.get("key_order")
                                            if key_order:
                                                print(f"     Doc ID: {doc_id[:8]}... (form_type 매칭 없음)")
                                                print(f"     page_keys ({len(key_order.get('page_keys', []))}개):")
                                                for i, key in enumerate(key_order.get('page_keys', []), 1):
                                                    print(f"       {i:2d}. {key}")
                                                print(f"     item_keys ({len(key_order.get('item_keys', []))}개):")
                                                for i, key in enumerate(key_order.get('item_keys', []), 1):
                                                    print(f"       {i:2d}. {key}")
                                                break
                            else:
                                print(f"  ⚠️  metadata 필드가 없습니다.")
                    else:
                        print(f"  ❌ DB에 해당 form_type의 인덱스가 없습니다.")
                    
                    # shard 인덱스도 확인
                    cursor.execute("""
                        SELECT index_name, metadata_json, updated_at
                        FROM rag_vector_index
                        WHERE index_name LIKE %s AND form_type = %s
                        ORDER BY updated_at DESC
                        LIMIT 5
                    """, (f'shard_%', form_type))
                    
                    shard_rows = cursor.fetchall()
                    if shard_rows:
                        print(f"  📦 Shard 인덱스 {len(shard_rows)}개 발견:")
                        for shard_row in shard_rows:
                            shard_index_name, shard_metadata_json, shard_updated_at = shard_row
                            print(f"     - {shard_index_name} (업데이트: {shard_updated_at})")
        
        except Exception as e:
            print(f"❌ DB 조회 실패: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("DB 모드가 비활성화되어 있습니다.")
    
    # RAG Manager의 get_key_order_by_form_type 메서드로 조회 테스트
    print("\n\n[RAG Manager 조회 테스트]")
    print("-" * 80)
    for form_type in form_types:
        print(f"\n📋 Form Type: {form_type}")
        key_order = rag_manager.get_key_order_by_form_type(form_type)
        if key_order:
            print(f"  ✅ key_order 조회 성공")
            print(f"     page_keys ({len(key_order.get('page_keys', []))}개):")
            for i, key in enumerate(key_order.get('page_keys', []), 1):
                print(f"       {i:2d}. {key}")
            print(f"     item_keys ({len(key_order.get('item_keys', []))}개):")
            for i, key in enumerate(key_order.get('item_keys', []), 1):
                print(f"       {i:2d}. {key}")
        else:
            print(f"  ❌ key_order를 찾을 수 없습니다.")
    
    print("\n" + "=" * 80)
    print("확인 완료")
    print("=" * 80)


if __name__ == "__main__":
    check_key_orders()
