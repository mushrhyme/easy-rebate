"""
아이템 관리 API
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel

from database.registry import get_db
from backend.api.routes.websocket import manager

router = APIRouter()


# 통계 API는 반드시 동적 경로보다 먼저 정의해야 함
@router.get("/stats/review")
async def get_review_stats(
    db=Depends(get_db)
):
    """
    검토 상태 통계 조회 (최적화: 인덱스 활용 및 쿼리 최적화)
    
    Returns:
        각 페이지별 1次/2次 검토 완료 여부 (모든 아이템이 체크되어야 완료)
        + 검토율 (체크된 아이템 수 / 전체 아이템 수)
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 각 페이지별 1次/2次 검토 상태 집계 (최적화: 인덱스 활용)
            # idx_items_pdf_page 인덱스를 활용하여 GROUP BY 성능 향상
            # items_current와 items_archive 모두 조회
            cursor.execute("""
                SELECT 
                    pdf_filename,
                    page_number,
                    -- 모든 아이템이 체크되어야 true
                    BOOL_AND(COALESCE(first_review_checked, false)) as first_reviewed,
                    BOOL_AND(COALESCE(second_review_checked, false)) as second_reviewed,
                    -- 검토율 계산용
                    COUNT(*) as total_count,
                    COUNT(*) FILTER (WHERE first_review_checked = true) as first_checked_count,
                    COUNT(*) FILTER (WHERE second_review_checked = true) as second_checked_count
                FROM (
                    SELECT pdf_filename, page_number, first_review_checked, second_review_checked
                    FROM items_current
                    UNION ALL
                    SELECT pdf_filename, page_number, first_review_checked, second_review_checked
                    FROM items_archive
                ) AS all_items
                GROUP BY pdf_filename, page_number
                ORDER BY pdf_filename, page_number
            """)
            rows = cursor.fetchall()
            
            # 페이지별 검토 상태
            page_stats = []
            first_reviewed_count = 0
            first_not_reviewed_count = 0
            second_reviewed_count = 0
            second_not_reviewed_count = 0
            
            for row in rows:
                pdf_filename, page_number, first_reviewed, second_reviewed, total_count, first_checked, second_checked = row
                first_reviewed = bool(first_reviewed) if first_reviewed is not None else False
                second_reviewed = bool(second_reviewed) if second_reviewed is not None else False
                
                # 검토율 계산 (퍼센트)
                first_review_rate = round((first_checked / total_count) * 100) if total_count > 0 else 0
                second_review_rate = round((second_checked / total_count) * 100) if total_count > 0 else 0
                
                page_stats.append({
                    "pdf_filename": pdf_filename,
                    "page_number": page_number,
                    "first_reviewed": first_reviewed,
                    "second_reviewed": second_reviewed,
                    "first_review_rate": first_review_rate,
                    "second_review_rate": second_review_rate,
                    "total_items": total_count,
                    "first_checked_count": first_checked,
                    "second_checked_count": second_checked
                })
                
                if first_reviewed:
                    first_reviewed_count += 1
                else:
                    first_not_reviewed_count += 1
                    
                if second_reviewed:
                    second_reviewed_count += 1
                else:
                    second_not_reviewed_count += 1
            
            return {
                "first_reviewed_count": first_reviewed_count,
                "first_not_reviewed_count": first_not_reviewed_count,
                "second_reviewed_count": second_reviewed_count,
                "second_not_reviewed_count": second_not_reviewed_count,
                "total_pages": len(page_stats),
                "page_stats": page_stats
            }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ItemCreateRequest(BaseModel):
    """아이템 생성 요청 모델"""
    pdf_filename: str
    page_number: int
    item_data: Dict[str, Any]  # 아이템 데이터 (customer, product_name, 기타 필드)
    customer: Optional[str] = None
    product_name: Optional[str] = None
    after_item_id: Optional[int] = None  # 특정 행 아래에 추가할 경우 해당 행의 item_id

class ItemUpdateRequest(BaseModel):
    """아이템 업데이트 요청 모델"""
    item_data: Dict[str, Any]  # 아이템 데이터 (customer, product_name, 기타 필드)
    review_status: Optional[Dict[str, Any]] = None  # 검토 상태
    expected_version: int  # 낙관적 락을 위한 예상 버전
    session_id: str  # 세션 ID


class ItemResponse(BaseModel):
    """아이템 응답 모델"""
    item_id: int
    pdf_filename: str
    page_number: int
    item_order: int
    customer: Optional[str] = None
    product_name: Optional[str] = None
    item_data: Dict[str, Any]
    review_status: Dict[str, Any]
    version: int


@router.get("/{pdf_filename}/pages/{page_number}")
async def get_page_items(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    특정 페이지의 아이템 목록 조회
    
    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        items = db.get_items(pdf_filename, page_number)
        
        # 응답 형식 변환
        # db.get_items()는 이미 모든 필드를 평탄화해서 반환하므로,
        # Streamlit 앱과 동일하게 모든 필드를 item_data에 포함
        item_list = []
        for item in items:
            # review_status 구성 (db.get_items()는 review_status 객체로 반환)
            existing_review_status = item.get('review_status', {})
            review_status = {
                "first_review": {
                    "checked": existing_review_status.get('first_review', {}).get('checked', False)
                },
                "second_review": {
                    "checked": existing_review_status.get('second_review', {}).get('checked', False)
                }
            }
            
            # item_data 추출: Streamlit 앱과 동일하게 메타데이터만 제외
            # Streamlit: display_item = {k: v for k, v in item.items() if k not in ['pdf_filename', 'page_number', 'form_type']}
            # 여기서는 item_data로 분리하되, 모든 데이터 필드를 포함
            item_data = {}
            exclude_keys = {
                'item_id', 'pdf_filename', 'page_number', 'item_order', 
                'version', 'form_type',
                'first_review_checked', 'second_review_checked',
                'first_reviewed_at', 'second_reviewed_at',
                'created_at', 'updated_at', 'review_status'
            }
            
            # customer와 product_name도 item_data에 포함 (Streamlit 앱과 동일)
            for key, value in item.items():
                if key not in exclude_keys:
                    item_data[key] = value
            
            item_list.append(ItemResponse(
                item_id=item['item_id'],
                pdf_filename=item['pdf_filename'],
                page_number=item['page_number'],
                item_order=item['item_order'],
                customer=item.get('customer'),
                product_name=item.get('product_name') or item.get('商品名'),  # DB에서 "商品名"으로 변환되어 있으므로 확인
                item_data=item_data,
                review_status=review_status,
                version=item.get('version', 1)
            ))
        
        return {"items": item_list}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def create_item(
    item_data: ItemCreateRequest,
    db=Depends(get_db)
):
    """
    새 아이템 생성

    Args:
        item_data: 생성할 아이템 데이터
        db: 데이터베이스 인스턴스
    """
    try:
        print(f"🔵 [create_item] 시작: pdf_filename={item_data.pdf_filename}, page_number={item_data.page_number}")
        
        # 문서 존재 확인
        doc = db.get_document(item_data.pdf_filename)
        if not doc:
            print(f"❌ [create_item] 문서를 찾을 수 없음: {item_data.pdf_filename}")
            raise HTTPException(status_code=404, detail="Document not found")

        # 페이지 존재 확인 (get_page_result는 느릴 수 있으므로 간단한 확인만 수행)
        # 실제로는 items가 있거나 문서가 있으면 페이지가 존재하는 것으로 간주
        try:
            # 페이지에 아이템이 있는지 간단히 확인
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM items_current 
                    WHERE pdf_filename = %s AND page_number = %s
                    UNION ALL
                    SELECT COUNT(*) 
                    FROM items_archive 
                    WHERE pdf_filename = %s AND page_number = %s
                """, (item_data.pdf_filename, item_data.page_number, item_data.pdf_filename, item_data.page_number))
                # UNION ALL 결과 합산
                item_count = sum(row[0] for row in cursor.fetchall())
                item_count = cursor.fetchone()[0]
                print(f"🔵 [create_item] 페이지 확인: pdf={item_data.pdf_filename}, page={item_data.page_number}, 기존 아이템 수={item_count}")
        except Exception as page_check_error:
            print(f"⚠️ [create_item] 페이지 확인 중 오류 (무시하고 계속): {page_check_error}")

        # 아이템 생성
        print(f"🔵 [create_item] 아이템 생성 시도: item_data={item_data.item_data}, after_item_id={item_data.after_item_id}")
        item_id = db.create_item(
            pdf_filename=item_data.pdf_filename,
            page_number=item_data.page_number,
            item_data=item_data.item_data,
            customer=item_data.customer,
            product_name=item_data.product_name,
            after_item_id=item_data.after_item_id
        )

        if item_id == -1:
            error_detail = "Failed to create item"
            if item_data.after_item_id:
                error_detail = f"Failed to create item: after_item_id={item_data.after_item_id} not found"
            print(f"❌ [create_item] 아이템 생성 실패: db.create_item이 -1 반환, after_item_id={item_data.after_item_id}")
            raise HTTPException(status_code=500, detail=error_detail)

        print(f"✅ [create_item] 아이템 생성 성공: item_id={item_id}")

        # 생성된 아이템 조회 (응답용)
        items = None
        created_item = None
        
        try:
            items = db.get_items(item_data.pdf_filename, item_data.page_number)
            print(f"🔵 [create_item] 조회된 아이템 수: {len(items)}")
            created_item = next((item for item in items if item.get('item_id') == item_id), None)
        except Exception as get_items_error:
            print(f"❌ [create_item] get_items 호출 실패: {get_items_error}")
            import traceback
            traceback.print_exc()
            # get_items 실패 시 직접 DB에서 조회 시도
            try:
                from psycopg2.extras import RealDictCursor
                import json
                
                with db.get_connection() as conn:
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    # current와 archive 모두에서 조회
                    cursor.execute("""
                        SELECT item_id, pdf_filename, page_number, item_order, customer, product_name,
                               first_review_checked, second_review_checked, item_data, version
                        FROM items_current
                        WHERE item_id = %s
                        UNION ALL
                        SELECT item_id, pdf_filename, page_number, item_order, customer, product_name,
                               first_review_checked, second_review_checked, item_data, version
                        FROM items_archive
                        WHERE item_id = %s
                        LIMIT 1
                    """, (item_id, item_id))
                    row = cursor.fetchone()
                    
                    if row:
                        created_item = dict(row)
                        # item_data 파싱
                        if isinstance(created_item.get('item_data'), str):
                            created_item['item_data'] = json.loads(created_item['item_data'])
                        elif not isinstance(created_item.get('item_data'), dict):
                            created_item['item_data'] = {}
                        
                        # review_status 구성
                        created_item['review_status'] = {
                            'first_review': {
                                'checked': created_item.get('first_review_checked', False),
                                'reviewed_at': None
                            },
                            'second_review': {
                                'checked': created_item.get('second_review_checked', False),
                                'reviewed_at': None
                            }
                        }
                        
                        items = [created_item]
                        print(f"✅ [create_item] 직접 DB 조회 성공: item_id={item_id}")
                    else:
                        print(f"❌ [create_item] 직접 DB 조회: item_id={item_id}인 아이템을 찾을 수 없음")
                        raise HTTPException(status_code=500, detail="Failed to retrieve created item: item not found in database")
            except HTTPException:
                raise
            except Exception as direct_query_error:
                print(f"❌ [create_item] 직접 DB 조회도 실패: {direct_query_error}")
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to retrieve created item: {str(direct_query_error)}")
        
        if not created_item:
            item_ids = [item.get('item_id') for item in items] if items else []
            print(f"❌ [create_item] 생성된 아이템을 조회할 수 없음: item_id={item_id}, 조회된 items={item_ids}")
            raise HTTPException(status_code=500, detail="Failed to retrieve created item")
        
        print(f"✅ [create_item] 생성된 아이템 조회 성공: item_id={item_id}, item_order={created_item.get('item_order')}")

        # 응답 형식 변환 (get_page_items와 동일)
        # get_items()는 review_status 객체로 반환하므로, 기존 review_status를 사용하거나 새로 구성
        existing_review_status = created_item.get('review_status', {})
        if existing_review_status:
            review_status = {
                "first_review": {
                    "checked": existing_review_status.get('first_review', {}).get('checked', False)
                },
                "second_review": {
                    "checked": existing_review_status.get('second_review', {}).get('checked', False)
                }
            }
        else:
            # review_status가 없는 경우 (하위 호환성)
            review_status = {
                "first_review": {
                    "checked": created_item.get('first_review_checked', False)
                },
                "second_review": {
                    "checked": created_item.get('second_review_checked', False)
                }
            }

        # item_data 추출
        exclude_keys = {
            'item_id', 'pdf_filename', 'page_number', 'item_order',
            'version', 'form_type',
            'first_review_checked', 'second_review_checked',
            'first_reviewed_at', 'second_reviewed_at',
            'created_at', 'updated_at', 'review_status',
            'customer', 'product_name', '商品名'  # customer와 product_name도 제외 (별도 필드로 전달)
        }

        response_item_data = {}
        for key, value in created_item.items():
            if key not in exclude_keys:
                response_item_data[key] = value

        # WebSocket 브로드캐스트 (새 아이템 생성 알림)
        await manager.broadcast_item_update(
            pdf_filename=item_data.pdf_filename,
            page_number=item_data.page_number,
            message={
                "type": "item_created",
                "item_id": item_id,
                "item_data": response_item_data
            }
        )

        # 필수 필드 검증
        item_order = created_item.get('item_order')
        if item_order is None:
            print(f"❌ [create_item] item_order가 없음: created_item keys={list(created_item.keys())}")
            raise HTTPException(status_code=500, detail="Missing required field: item_order")
        
        version = created_item.get('version', 1)
        customer = created_item.get('customer') or created_item.get('customer')
        product_name = created_item.get('product_name') or created_item.get('商品名')
        
        print(f"🔵 [create_item] ItemResponse 생성: item_order={item_order}, version={version}, customer={customer}, product_name={product_name}")
        
        try:
            response = ItemResponse(
                item_id=item_id,
                pdf_filename=item_data.pdf_filename,
                page_number=item_data.page_number,
                item_order=item_order,
                customer=customer,
                product_name=product_name,
                item_data=response_item_data,
                review_status=review_status,
                version=version
            )
            print(f"✅ [create_item] ItemResponse 생성 성공")
            return response
        except Exception as validation_error:
            print(f"❌ [create_item] ItemResponse 생성 실패: {validation_error}")
            print(f"   item_id={item_id}, item_order={item_order}, version={version}")
            print(f"   review_status={review_status}")
            print(f"   response_item_data keys={list(response_item_data.keys())}")
            raise HTTPException(status_code=500, detail=f"Failed to create response: {str(validation_error)}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [create_item] 예외 발생: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{item_id}")
async def update_item(
    item_id: int,
    update_data: ItemUpdateRequest,
    db=Depends(get_db)
):
    """
    아이템 업데이트 (낙관적 락 적용)
    
    Args:
        item_id: 아이템 ID
        update_data: 업데이트 요청 데이터 (item_data, review_status, expected_version, session_id 포함)
        db: 데이터베이스 인스턴스
    """
    print(f"🔵 [백엔드] update_item 호출: item_id={item_id}, review_status={update_data.review_status}")
    try:
        # update_data에서 필요한 필드 추출
        expected_version = update_data.expected_version
        session_id = update_data.session_id
        
        # 아이템 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # current와 archive 모두에서 조회
            cursor.execute("""
                SELECT item_id, pdf_filename, page_number, version
                FROM items_current
                WHERE item_id = %s
                UNION ALL
                SELECT item_id, pdf_filename, page_number, version
                FROM items_archive
                WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item = cursor.fetchone()
            
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            
            # 버전 확인
            current_version = item[3]
            if current_version != expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Version conflict. Another user has modified this item."
                )
            
            # 락 확인 (get_items_with_lock_status 사용)
            items_with_locks = db.get_items_with_lock_status(
                pdf_filename=item[1],
                page_number=item[2],
                current_session_id=session_id
            )
            # 현재 아이템의 락 상태 확인
            item_lock_info = next(
                (i for i in items_with_locks if i.get('item_id') == item_id),
                None
            )
            if item_lock_info and item_lock_info.get('is_locked_by_others'):
                locked_by_user_id = item_lock_info.get('locked_by_user_id')
                # user_id가 None인 경우는 만료되었거나 잘못된 락이므로 무시
                if locked_by_user_id is None:
                    print(f"⚠️ [백엔드] user_id가 None인 락 발견 - 무시하고 계속 진행: item_id={item_id}")
                else:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Item is locked by another user: user_id={locked_by_user_id}"
                    )
            
            # 필드 분리
            separated = db._separate_item_fields(update_data.item_data)
            
            # 업데이트 쿼리 구성
            set_clauses = []
            params = []
            
            if 'customer' in separated and separated['customer'] is not None:
                set_clauses.append("customer = %s")
                params.append(separated['customer'])
            
            if 'product_name' in separated and separated['product_name'] is not None:
                set_clauses.append("product_name = %s")
                params.append(separated['product_name'])
            
            # 검토 상태 업데이트
            if update_data.review_status:
                print(f"🔵 [백엔드] review_status 업데이트: {update_data.review_status}")
                first_review = update_data.review_status.get('first_review', {})
                second_review = update_data.review_status.get('second_review', {})
                
                if 'checked' in first_review:
                    checked_value = first_review['checked']
                    print(f"🔵 [백엔드] first_review_checked = {checked_value} (type: {type(checked_value)})")
                    set_clauses.append("first_review_checked = %s")
                    params.append(bool(checked_value))  # 명시적으로 boolean으로 변환
                
                if 'checked' in second_review:
                    checked_value = second_review['checked']
                    print(f"🔵 [백엔드] second_review_checked = {checked_value} (type: {type(checked_value)})")
                    set_clauses.append("second_review_checked = %s")
                    params.append(bool(checked_value))  # 명시적으로 boolean으로 변환
            
            # JSONB 필드 업데이트
            if 'item_data' in separated:
                set_clauses.append("item_data = %s::jsonb")
                import json
                params.append(json.dumps(separated['item_data'], ensure_ascii=False))
            
            # 버전 증가 및 업데이트 시간
            set_clauses.append("version = version + 1")
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            # WHERE 조건
            params.append(item_id)
            params.append(expected_version)
            
            if not set_clauses:
                raise HTTPException(status_code=400, detail="No fields to update")
            
            # item_id가 어느 테이블에 있는지 확인
            cursor.execute("""
                SELECT 'current' as table_type FROM items_current WHERE item_id = %s
                UNION ALL
                SELECT 'archive' as table_type FROM items_archive WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item_location = cursor.fetchone()
            table_suffix = item_location[0] if item_location else 'current'  # 기본값은 current
            items_table = f"items_{table_suffix}"
            
            sql = f"""
                UPDATE {items_table} 
                SET {', '.join(set_clauses)}
                WHERE item_id = %s
                  AND version = %s
            """
            
            print(f"🔵 [백엔드] SQL 실행: {sql}")
            print(f"🔵 [백엔드] 파라미터: {params}")
            cursor.execute(sql, params)
            
            if cursor.rowcount == 0:
                print(f"❌ [백엔드] 업데이트 실패: rowcount=0")
                raise HTTPException(
                    status_code=409,
                    detail="Version conflict or item not found"
                )
            
            # 락 해제 (체크박스 업데이트는 락이 없을 수 있으므로 실패해도 계속 진행)
            try:
                db.release_item_lock(item_id, session_id)
            except Exception as lock_error:
                # 락 해제 실패는 경고만 출력 (체크박스 업데이트는 락 없이도 가능)
                print(f"⚠️ [백엔드] 락 해제 실패 (무시): {lock_error}")
            
            conn.commit()
            print(f"✅ [백엔드] DB 업데이트 완료: item_id={item_id}, rowcount={cursor.rowcount}")
            
            # 저장된 값 확인 (items_current 또는 items_archive에서 조회)
            cursor.execute(f"""
                SELECT first_review_checked, second_review_checked
                FROM {items_table}
                WHERE item_id = %s
            """, (item_id,))
            saved_values = cursor.fetchone()
            print(f"✅ [백엔드] 저장된 값 확인: first={saved_values[0]}, second={saved_values[1]}")
            
            # review_status 업데이트 시 WebSocket으로 브로드캐스트
            if update_data.review_status:
                print(f"🔵 [백엔드] WebSocket 브로드캐스트 시작: pdf_filename={item[1]}, page_number={item[2]}")
                await manager.broadcast_lock_update(
                    pdf_filename=item[1],
                    page_number=item[2],
                    message={
                        "type": "review_status_updated",
                        "item_id": item_id,
                        "review_status": update_data.review_status,
                    }
                )
                print(f"✅ [백엔드] WebSocket 브로드캐스트 완료")
        
        print(f"✅ [백엔드] update_item 성공: item_id={item_id}")
        return {"message": "Item updated successfully", "item_id": item_id}
    
    except HTTPException as e:
        print(f"❌ [백엔드] HTTPException: status={e.status_code}, detail={e.detail}")
        raise
    except Exception as e:
        print(f"❌ [백엔드] Exception: {type(e).__name__}, {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/lock")
async def acquire_item_lock(
    item_id: int,
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    아이템 락 획득
    
    Args:
        item_id: 아이템 ID
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        print(f"🔵 [acquire_item_lock] 시작: item_id={item_id}, session_id={session_id[:8] if session_id else 'None'}...")
        
        # session_id 검증
        if not session_id or not isinstance(session_id, str) or len(session_id.strip()) == 0:
            print(f"❌ [acquire_item_lock] session_id 검증 실패: session_id={session_id}")
            raise HTTPException(
                status_code=422,
                detail="session_id is required and must be a non-empty string"
            )
        
        # 아이템 존재 확인 및 정보 조회 (브로드캐스트용)
        item_info = None
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT pdf_filename, page_number
                    FROM items_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT pdf_filename, page_number
                    FROM items_archive
                    WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))
                item_info = cursor.fetchone()
                
                if not item_info:
                    print(f"❌ [acquire_item_lock] 아이템을 찾을 수 없음: item_id={item_id}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"Item not found: item_id={item_id}"
                    )
                
                print(f"✅ [acquire_item_lock] 아이템 확인: item_id={item_id}, pdf={item_info[0]}, page={item_info[1]}")
        except HTTPException:
            raise
        except Exception as item_check_error:
            print(f"❌ [acquire_item_lock] 아이템 조회 중 오류: {item_check_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check item: {str(item_check_error)}"
            )
        
        # 락 획득 시도 (만료된 락 강제 정리 포함)
        print(f"🔵 [acquire_item_lock] 락 획득 시도: item_id={item_id}")
        success, reason = db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
        print(f"🔵 [acquire_item_lock] 락 획득 결과: success={success}, reason={reason}")
        
        # 락 획득 성공 시 브로드캐스트
        if success and item_info:
            print(f"🔒 [락 획득] item_id={item_id}, session_id={session_id[:8]}..., pdf={item_info[0]}, page={item_info[1]}")
            try:
                await manager.broadcast_lock_update(
                    pdf_filename=item_info[0],
                    page_number=item_info[1],
                    message={
                        "type": "lock_acquired",
                        "item_id": item_id,
                        "session_id": session_id,
                    }
                )
                print(f"✅ [락 획득] 브로드캐스트 호출 완료")
            except Exception as broadcast_error:
                print(f"⚠️ [락 획득] 브로드캐스트 실패 (무시): {broadcast_error}")
        
        if not success:
            # 락 정보 조회
            print(f"❌ [acquire_item_lock] 락 획득 실패: item_id={item_id}, reason={reason}")
            if item_info:
                try:
                    items_with_locks = db.get_items_with_lock_status(
                        pdf_filename=item_info[0],
                        page_number=item_info[1],
                        current_session_id=session_id
                    )
                    item_lock_info = next(
                        (i for i in items_with_locks if i.get('item_id') == item_id),
                        None
                    )
                    if item_lock_info:
                        locked_by_user_id = item_lock_info.get('locked_by_user_id')
                        is_locked_by_others = item_lock_info.get('is_locked_by_others', False)
                        
                        # user_id가 None이거나 is_locked_by_others가 False인 경우는 잘못된 락이므로 무시하고 재시도
                        if locked_by_user_id is None or not is_locked_by_others:
                            print(f"⚠️ [acquire_item_lock] 잘못된 락 발견 (user_id={locked_by_user_id}, is_locked_by_others={is_locked_by_others}) - 강제 정리 후 재시도: item_id={item_id}")
                            # 만료된 락 강제 정리 후 재시도
                            try:
                                with db.get_connection() as conn:
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                        DELETE FROM item_locks_current WHERE item_id = %s
                                    """, (item_id,))
                                    cursor.execute("""
                                        DELETE FROM item_locks_archive WHERE item_id = %s
                                    """, (item_id,))
                                    conn.commit()
                                # 재시도
                                retry_success, retry_reason = db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
                                if retry_success:
                                    return {"message": "Lock acquired successfully", "item_id": item_id}
                                else:
                                    print(f"⚠️ [acquire_item_lock] 재시도 후에도 실패: item_id={item_id}, reason={retry_reason}")
                                    reason = retry_reason  # 재시도 실패 원인으로 업데이트
                            except Exception as cleanup_error:
                                print(f"⚠️ [acquire_item_lock] 락 정리 실패: {cleanup_error}")
                        else:
                            print(f"❌ [acquire_item_lock] 다른 사용자가 락을 보유: locked_by_user_id={locked_by_user_id}")
                            raise HTTPException(
                                status_code=409,
                                detail=f"Item is locked by another user: user_id={locked_by_user_id}"
                            )
                except HTTPException:
                    raise
                except Exception as lock_info_error:
                    print(f"⚠️ [acquire_item_lock] 락 정보 조회 실패: {lock_info_error}")
            
            # 실패 원인 메시지 사용 (reason은 위에서 이미 받았으므로 사용 가능)
            error_detail = reason if reason else "Failed to acquire lock"
            print(f"❌ [acquire_item_lock] 락 획득 실패: item_id={item_id}, reason={error_detail}")
            raise HTTPException(
                status_code=409,
                detail=error_detail
            )

        return {"message": "Lock acquired successfully", "item_id": item_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    db=Depends(get_db)
):
    """
    아이템 삭제

    Args:
        item_id: 삭제할 아이템 ID
        db: 데이터베이스 인스턴스
    """
    try:
        print(f"🔵 [delete_item] 시작: item_id={item_id}, type={type(item_id)}")
        
        # 아이템 존재 여부 및 정보 조회 (WebSocket 브로드캐스트용)
        # delete_item 메서드 내부에서도 조회하지만, 여기서 먼저 확인
        item_info = None
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # 먼저 아이템이 존재하는지 확인
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT item_id, pdf_filename, page_number, item_order
                    FROM items_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT item_id, pdf_filename, page_number, item_order
                    FROM items_archive
                    WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))
                item_info = cursor.fetchone()
                print(f"🔵 [delete_item] DB 쿼리 결과: item_info={item_info}")
                
                if item_info:
                    print(f"✅ [delete_item] 아이템 발견: item_id={item_info[0]}, pdf={item_info[1]}, page={item_info[2]}")
                else:
                    # 디버깅: 전체 아이템 목록 확인
                    cursor.execute("""
                        SELECT item_id, pdf_filename, page_number
                        FROM items_current
                        ORDER BY item_id DESC
                        LIMIT 10
                    """)
                    all_items = cursor.fetchall()
                    print(f"🔍 [delete_item] 최근 10개 아이템: {all_items}")
        except Exception as query_error:
            print(f"❌ [delete_item] 아이템 조회 중 오류: {query_error}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Database query error: {str(query_error)}")

        if not item_info:
            print(f"❌ [delete_item] 아이템을 찾을 수 없음: item_id={item_id}")
            raise HTTPException(status_code=404, detail="Item not found")

        pdf_filename, page_number = item_info[1], item_info[2]
        print(f"✅ [delete_item] 아이템 정보: pdf_filename={pdf_filename}, page_number={page_number}")

        # 아이템 삭제
        print(f"🔵 [delete_item] db.delete_item 호출: item_id={item_id}")
        success = db.delete_item(item_id=item_id)
        print(f"🔵 [delete_item] db.delete_item 결과: success={success}")

        if not success:
            print(f"❌ [delete_item] 아이템 삭제 실패: item_id={item_id}")
            raise HTTPException(status_code=500, detail="Failed to delete item")

        print(f"✅ [delete_item] 아이템 삭제 성공: item_id={item_id}")

        # WebSocket 브로드캐스트 (아이템 삭제 알림)
        try:
            await manager.broadcast_item_update(
                pdf_filename=pdf_filename,
                page_number=page_number,
                message={
                    "type": "item_deleted",
                    "item_id": item_id
                }
            )
            print(f"✅ [delete_item] WebSocket 브로드캐스트 완료")
        except Exception as ws_error:
            print(f"⚠️ [delete_item] WebSocket 브로드캐스트 실패 (무시): {ws_error}")

        return {"message": "Item deleted successfully", "item_id": item_id}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [delete_item] 예외 발생: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{item_id}/lock")
async def release_item_lock(
    item_id: int,
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    아이템 락 해제
    
    Args:
        item_id: 아이템 ID
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        # 아이템 정보 먼저 조회 (브로드캐스트용) - items_current 또는 items_archive에서 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, page_number
                FROM items_current
                WHERE item_id = %s
                UNION ALL
                SELECT pdf_filename, page_number
                FROM items_archive
                WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item_info = cursor.fetchone()
        
        success = db.release_item_lock(item_id=item_id, session_id=session_id)
        
        # 락 해제 성공 시 브로드캐스트
        if success and item_info:
            print(f"🔓 [락 해제] item_id={item_id}, session_id={session_id[:8]}..., pdf={item_info[0]}, page={item_info[1]}")
            await manager.broadcast_lock_update(
                pdf_filename=item_info[0],
                page_number=item_info[1],
                message={
                    "type": "lock_released",
                    "item_id": item_id,
                    "session_id": session_id,
                }
            )
            print(f"✅ [락 해제] 브로드캐스트 호출 완료")
        
        if not success:
            raise HTTPException(
                status_code=422,
                detail="Lock not found or already released"
            )
        
        return {"message": "Lock released successfully", "item_id": item_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/locks/session")
async def release_all_locks_by_session(
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    세션 ID로 잠긴 모든 락 해제 (페이지 언로드 시 사용)
    
    Args:
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        # session_id를 user_id로 변환
        user_info = db.get_session_user(session_id)
        if not user_info:
            return {"message": "Session not found", "released_count": 0}
        
        user_id = user_info['user_id']
        
        # 해제할 락들의 정보 조회 (브로드캐스트용)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                FROM item_locks_current l
                INNER JOIN items_current i ON l.item_id = i.item_id
                WHERE l.locked_by_user_id = %s
                UNION ALL
                SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                FROM item_locks_archive l
                INNER JOIN items_archive i ON l.item_id = i.item_id
                WHERE l.locked_by_user_id = %s
            """, (user_id, user_id))
            locks_info = cursor.fetchall()
        
        # 모든 락 해제
        released_count = db.release_all_locks_by_session(session_id=session_id)
        
        # 각 페이지별로 브로드캐스트
        if released_count > 0:
            # 페이지별로 그룹화
            page_locks: Dict[tuple, List[int]] = {}
            for pdf_filename, page_number, item_id in locks_info:
                key = (pdf_filename, page_number)
                if key not in page_locks:
                    page_locks[key] = []
                page_locks[key].append(item_id)
            
            # 각 페이지에 대해 브로드캐스트
            for (pdf_filename, page_number), item_ids in page_locks.items():
                for item_id in item_ids:
                    await manager.broadcast_lock_update(
                        pdf_filename=pdf_filename,
                        page_number=page_number,
                        message={
                            "type": "lock_released",
                            "item_id": item_id,
                            "session_id": session_id,
                        }
                    )
            print(f"✅ [세션 락 해제] 브로드캐스트 완료: {released_count}개 락 해제")
        
        return {"message": "All locks released successfully", "released_count": released_count}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
