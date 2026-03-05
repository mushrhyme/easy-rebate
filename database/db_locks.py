"""
락 관리 Mixin

아이템 락 관련 데이터베이스 작업을 담당합니다.
"""
from typing import Dict, Any, List, Optional
from psycopg2.extras import RealDictCursor
from database.table_selector import get_table_name


class LocksMixin:
    """아이템 락 관리 Mixin"""
    
    def acquire_item_lock(
        self,
        item_id: int,
        session_id: str,
        lock_duration_minutes: int = 30,
        force_cleanup: bool = True
    ) -> tuple[bool, str]:
        """
        특정 행에 락 획득 시도 (item_id 기준)
        
        Args:
            item_id: 행 ID
            session_id: 세션 ID (user_id로 변환하여 저장)
            lock_duration_minutes: 락 유지 시간 (분, 기본 30분)
            force_cleanup: 만료된 락 강제 정리 여부 (기본 True)
            
        Returns:
            (락 획득 성공 여부, 실패 원인 메시지)
        """
        try:
            from datetime import datetime, timedelta
            
            print(f"🔵 [acquire_item_lock] 시작: item_id={item_id}, session_id={session_id[:8] if session_id else 'None'}..., duration={lock_duration_minutes}분")
            
            # session_id 검증
            if not session_id or not isinstance(session_id, str) or len(session_id.strip()) == 0:
                print(f"❌ [acquire_item_lock] session_id가 유효하지 않음: session_id={session_id}")
                return False, "Session expired or invalid. Please refresh the page."
            
            # session_id로 user_id 조회
            print(f"🔵 [acquire_item_lock] 세션 조회 시도: session_id={session_id[:20]}...")
            user_info = self.get_session_user(session_id)
            if not user_info:
                print(f"❌ [acquire_item_lock] 세션을 찾을 수 없음: session_id={session_id[:20] if session_id else 'None'}...")
                return False, "Session expired or invalid. Please refresh the page."
            
            user_id = user_info['user_id']
            print(f"✅ [acquire_item_lock] 사용자 확인: user_id={user_id}")
            
            # 아이템 존재 확인 + 락 처리 한 연결로 수행 (풀 점유 시간 단축)
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item_id FROM items_current WHERE item_id = %s
                    UNION ALL
                    SELECT item_id FROM items_archive WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))
                if not cursor.fetchone():
                    print(f"❌ [acquire_item_lock] 아이템이 존재하지 않음: item_id={item_id}")
                    return False, f"Item not found: item_id={item_id}"
                print(f"✅ [acquire_item_lock] 아이템 존재 확인: item_id={item_id}")
                
                # 1. 해당 item_id의 모든 락 확인 및 정리 (current와 archive 모두 확인)
                cursor.execute("""
                    SELECT locked_by_user_id, expires_at, locked_at
                    FROM item_locks_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT locked_by_user_id, expires_at, locked_at
                    FROM item_locks_archive
                    WHERE item_id = %s
                """, (item_id, item_id))
                
                all_locks = cursor.fetchall()
                print(f"🔵 [acquire_item_lock] 기존 락 확인: {len(all_locks)}개")
                
                # 1-1. 만료된 락 모두 정리 (current와 archive 모두)
                cursor.execute("""
                    DELETE FROM item_locks_current
                    WHERE item_id = %s
                      AND expires_at < CURRENT_TIMESTAMP
                """, (item_id,))
                deleted_expired_current = cursor.rowcount
                
                cursor.execute("""
                    DELETE FROM item_locks_archive
                    WHERE item_id = %s
                      AND expires_at < CURRENT_TIMESTAMP
                """, (item_id,))
                deleted_expired_archive = cursor.rowcount
                
                deleted_expired = deleted_expired_current + deleted_expired_archive
                if deleted_expired > 0:
                    print(f"🔵 [acquire_item_lock] 만료된 락 정리: {deleted_expired}개")
                
                # 1-2. 추가로 모든 만료된 락 정리 (혹시 모를 경우 대비)
                if force_cleanup:
                    cursor.execute("""
                        DELETE FROM item_locks_current
                        WHERE expires_at < CURRENT_TIMESTAMP
                    """)
                    cursor.execute("""
                        DELETE FROM item_locks_archive
                        WHERE expires_at < CURRENT_TIMESTAMP
                    """)
                
                # 1-3. 오래된 락도 정리 (locked_at이 1시간 이상 지난 락은 강제 정리)
                cursor.execute("""
                    DELETE FROM item_locks_current
                    WHERE item_id = %s
                      AND locked_at < CURRENT_TIMESTAMP - INTERVAL '1 hour'
                """, (item_id,))
                cursor.execute("""
                    DELETE FROM item_locks_archive
                    WHERE item_id = %s
                      AND locked_at < CURRENT_TIMESTAMP - INTERVAL '1 hour'
                """, (item_id,))
                
                # 2. 기존 락 확인 (만료되지 않은 것만, current와 archive 모두 확인)
                cursor.execute("""
                    SELECT locked_by_user_id, expires_at
                    FROM item_locks_current
                    WHERE item_id = %s
                      AND expires_at >= CURRENT_TIMESTAMP
                    UNION ALL
                    SELECT locked_by_user_id, expires_at
                    FROM item_locks_archive
                    WHERE item_id = %s
                      AND expires_at >= CURRENT_TIMESTAMP
                    LIMIT 1
                """, (item_id, item_id))
                
                existing_lock = cursor.fetchone()
                
                if existing_lock:
                    existing_locked_by_user_id = existing_lock[0]
                    expires_at_value = existing_lock[1]
                    print(f"🔵 [acquire_item_lock] 기존 활성 락 발견: locked_by_user_id={existing_locked_by_user_id}, expires_at={expires_at_value}")
                    
                    # locked_by_user_id가 None인 경우는 잘못된 락이므로 정리하고 새 락 생성
                    if existing_locked_by_user_id is None:
                        print(f"⚠️ [acquire_item_lock] user_id가 None인 락 발견 - 강제 정리: item_id={item_id}")
                        cursor.execute("""
                            DELETE FROM item_locks_current
                            WHERE item_id = %s
                        """, (item_id,))
                        cursor.execute("""
                            DELETE FROM item_locks_archive
                            WHERE item_id = %s
                        """, (item_id,))
                        conn.commit()
                        # 새 락 생성으로 계속 진행 (아래 로직으로 넘어감)
                        print(f"🔵 [acquire_item_lock] 잘못된 락 정리 후 새 락 생성 계속: item_id={item_id}")
                        # existing_lock을 None으로 설정하여 새 락 생성 로직으로 넘어가도록 함
                        existing_lock = None
                    # 자신이 가진 락이면 갱신
                    elif existing_locked_by_user_id == user_id:
                        expires_at = datetime.now() + timedelta(minutes=lock_duration_minutes)
                        # current와 archive 모두 확인하여 업데이트
                        cursor.execute("""
                            UPDATE item_locks_current
                            SET expires_at = %s,
                                locked_at = CURRENT_TIMESTAMP
                            WHERE item_id = %s
                              AND locked_by_user_id = %s
                        """, (expires_at, item_id, user_id))
                        if cursor.rowcount == 0:
                            cursor.execute("""
                                UPDATE item_locks_archive
                                SET expires_at = %s,
                                    locked_at = CURRENT_TIMESTAMP
                                WHERE item_id = %s
                                  AND locked_by_user_id = %s
                            """, (expires_at, item_id, user_id))
                        conn.commit()
                        print(f"✅ [acquire_item_lock] 자신의 락 갱신 성공: item_id={item_id}")
                        return True, "Lock acquired successfully"
                    else:
                        # 다른 사용자가 가진 락이 있지만, 만료 시간이 가까우면 강제로 정리
                        if isinstance(expires_at_value, datetime):
                            time_until_expiry = (expires_at_value - datetime.now()).total_seconds() / 60
                            # 만료까지 5분 이하 남았으면 강제로 정리 (오래된 락으로 간주)
                            if time_until_expiry <= 5:
                                print(f"⚠️ [acquire_item_lock] 오래된 락 감지 (만료까지 {time_until_expiry:.1f}분 남음), 강제 정리: item_id={item_id}, locked_by_user_id={existing_locked_by_user_id}")
                                cursor.execute("""
                                    DELETE FROM item_locks_current
                                    WHERE item_id = %s
                                """, (item_id,))
                                cursor.execute("""
                                    DELETE FROM item_locks_archive
                                    WHERE item_id = %s
                                """, (item_id,))
                                conn.commit()
                                # 재시도
                                print(f"🔵 [acquire_item_lock] 재시도: item_id={item_id}")
                                success, reason = self.acquire_item_lock(item_id, session_id, lock_duration_minutes, force_cleanup=False)
                                return success, reason
                        # 다른 사용자의 활성 락
                        print(f"⚠️ [acquire_item_lock] 다른 사용자의 활성 락: item_id={item_id}, locked_by_user_id={existing_locked_by_user_id}, expires_at={expires_at_value}")
                        return False, f"Item is locked by another user (user_id={existing_locked_by_user_id})"
                
                # 3. 새 락 생성 (락이 없거나 만료된 경우, 또는 user_id가 None인 락을 정리한 경우)
                # existing_lock이 None이거나 user_id가 None인 락을 정리한 경우 새 락 생성
                if not existing_lock or (existing_lock and existing_lock[0] is None):
                    # item_id가 current 또는 archive에 있는지 확인하여 해당 테이블에 저장
                    print(f"🔵 [acquire_item_lock] 새 락 생성 시도: item_id={item_id}")
                    expires_at = datetime.now() + timedelta(minutes=lock_duration_minutes)

                    # item_id가 어느 테이블에 있는지 확인
                    cursor.execute("""
                        SELECT 'current' as table_type FROM items_current WHERE item_id = %s
                        UNION ALL
                        SELECT 'archive' as table_type FROM items_archive WHERE item_id = %s
                        LIMIT 1
                    """, (item_id, item_id))
                    item_location = cursor.fetchone()
                    table_suffix = item_location[0] if item_location else 'current'  # 기본값은 current
                    locks_table = f"item_locks_{table_suffix}"

                    try:
                        cursor.execute(f"""
                            INSERT INTO {locks_table} (item_id, locked_by_user_id, expires_at)
                            VALUES (%s, %s, %s)
                        """, (item_id, user_id, expires_at))

                        if cursor.rowcount > 0:
                            conn.commit()
                            print(f"✅ [acquire_item_lock] 새 락 생성 성공: item_id={item_id}, locked_by_user_id={user_id}, expires_at={expires_at}")
                            return True, "Lock acquired successfully"
                        else:
                            # INSERT 실패 - 다시 확인
                            print(f"⚠️ [acquire_item_lock] INSERT 실패 (rowcount=0): item_id={item_id}, 재확인")
                            cursor.execute("""
                                SELECT locked_by_user_id, expires_at
                                FROM item_locks_current
                                WHERE item_id = %s
                                UNION ALL
                                SELECT locked_by_user_id, expires_at
                                FROM item_locks_archive
                                WHERE item_id = %s
                                LIMIT 1
                            """, (item_id, item_id))
                            check_lock = cursor.fetchone()
                            if check_lock:
                                check_locked_by_user_id = check_lock[0]
                                if check_locked_by_user_id == user_id:
                                    conn.commit()
                                    print(f"✅ [acquire_item_lock] 재확인 후 성공: item_id={item_id}")
                                    return True, "Lock acquired successfully"
                                else:
                                    print(f"⚠️ [acquire_item_lock] 재확인 후 다른 사용자 락 발견: item_id={item_id}, locked_by_user_id={check_locked_by_user_id}")
                                    return False, f"Item is locked by another user (user_id={check_locked_by_user_id})"
                            else:
                                # 락이 없는데 INSERT가 실패한 경우 - 재시도
                                print(f"⚠️ [acquire_item_lock] 락 생성 실패 (락 없음): item_id={item_id}, 재시도")
                                conn.rollback()
                                success, reason = self.acquire_item_lock(item_id, session_id, lock_duration_minutes, force_cleanup=False)
                                return success, reason
                    except Exception as insert_error:
                        # INSERT 실패 (예: 외래 키 제약조건 위반 등)
                        print(f"❌ [acquire_item_lock] INSERT 예외 발생: {type(insert_error).__name__}: {insert_error}")
                        import traceback
                        traceback.print_exc()
                        conn.rollback()
                        # 다시 확인
                        cursor.execute("""
                            SELECT locked_by_user_id, expires_at
                            FROM item_locks_current
                            WHERE item_id = %s
                            UNION ALL
                            SELECT locked_by_user_id, expires_at
                            FROM item_locks_archive
                            WHERE item_id = %s
                            LIMIT 1
                        """, (item_id, item_id))
                        check_lock = cursor.fetchone()
                        if check_lock and check_lock[0] == user_id:
                            conn.commit()
                            print(f"✅ [acquire_item_lock] 예외 후 재확인 성공: item_id={item_id}")
                            return True, "Lock acquired successfully"
                        print(f"❌ [acquire_item_lock] 최종 실패: item_id={item_id}")
                        return False, f"Failed to create lock: {str(insert_error)}"
        except Exception as e:
            print(f"⚠️ 락 획득 실패: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Lock acquisition error: {str(e)}"
    
    def release_item_lock(
        self,
        item_id: int,
        session_id: str
    ) -> bool:
        """
        특정 행의 락 해제 (item_id 기준)
        
        Args:
            item_id: 행 ID
            session_id: 세션 ID (user_id로 변환하여 비교)
            
        Returns:
            락 해제 성공 여부
        """
        try:
            # session_id로 user_id 조회
            user_info = self.get_session_user(session_id)
            if not user_info:
                print(f"❌ [release_item_lock] 세션을 찾을 수 없음: session_id={session_id[:8] if session_id else 'None'}...")
                return False
            
            user_id = user_info['user_id']
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 삭제
                cursor.execute("""
                    DELETE FROM item_locks_current
                    WHERE item_id = %s
                      AND locked_by_user_id = %s
                """, (item_id, user_id))
                deleted_current = cursor.rowcount
                
                cursor.execute("""
                    DELETE FROM item_locks_archive
                    WHERE item_id = %s
                      AND locked_by_user_id = %s
                """, (item_id, user_id))
                deleted_archive = cursor.rowcount
                
                conn.commit()
                return (deleted_current + deleted_archive) > 0
        except Exception as e:
            print(f"⚠️ 락 해제 실패: {e}")
            return False
    
    def release_all_locks_by_session(
        self,
        session_id: str
    ) -> int:
        """
        특정 세션 ID로 잠긴 모든 락 해제 (페이지 언로드 시 사용)
        
        Args:
            session_id: 세션 ID (user_id로 변환하여 삭제)
            
        Returns:
            해제된 락 개수
        """
        try:
            # session_id로 user_id 조회
            user_info = self.get_session_user(session_id)
            if not user_info:
                print(f"❌ [release_all_locks_by_session] 세션을 찾을 수 없음: session_id={session_id[:8] if session_id else 'None'}...")
                return 0
            
            user_id = user_info['user_id']
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 삭제
                cursor.execute("""
                    DELETE FROM item_locks_current
                    WHERE locked_by_user_id = %s
                """, (user_id,))
                deleted_current = cursor.rowcount
                
                cursor.execute("""
                    DELETE FROM item_locks_archive
                    WHERE locked_by_user_id = %s
                """, (user_id,))
                deleted_archive = cursor.rowcount
                
                deleted_count = deleted_current + deleted_archive
                conn.commit()
                if deleted_count > 0:
                    print(f"🔓 [세션 락 해제] user_id={user_id}, 해제된 락: {deleted_count}개")
                return deleted_count
        except Exception as e:
            print(f"⚠️ 세션 락 해제 실패: {e}")
            return 0
    
    def get_items_with_lock_status(
        self,
        pdf_filename: str,
        page_number: int,
        current_session_id: str,
        year: Optional[int] = None,
        month: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        페이지의 모든 행과 락 상태를 함께 조회 (LEFT JOIN)
        만료된 락은 자동으로 정리하고 조회하지 않음
        
        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호
            current_session_id: 현재 세션 ID (user_id로 변환하여 비교)
            year: 연도 (선택사항, 테이블 선택용)
            month: 월 (선택사항, 테이블 선택용)
            
        Returns:
            행 리스트 (락 상태 포함)
        """
        try:
            # session_id로 user_id 조회
            user_info = self.get_session_user(current_session_id)
            current_user_id = user_info['user_id'] if user_info else None
            
            # 연월에 따라 테이블 선택
            if year is not None and month is not None:
                items_table = get_table_name('items', year, month)
                locks_table = get_table_name('item_locks', year, month)
            else:
                # current에서 먼저 찾고, 없으면 archive에서 찾기
                items_table = "items_current"
                locks_table = "item_locks_current"
            
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 만료된 락 정리 (current와 archive 모두)
                cursor.execute("""
                    DELETE FROM item_locks_current
                    WHERE expires_at < CURRENT_TIMESTAMP
                """)
                cursor.execute("""
                    DELETE FROM item_locks_archive
                    WHERE expires_at < CURRENT_TIMESTAMP
                """)
                conn.commit()
                
                cursor.execute(f"""
                    SELECT 
                        i.item_id,
                        i.pdf_filename,
                        i.page_number,
                        i.item_order,
                        i.first_review_checked,
                        i.second_review_checked,
                        i.first_reviewed_at,
                        i.second_reviewed_at,
                        i.item_data,
                        i.version,
                        l.locked_by_user_id,
                        l.locked_at,
                        l.expires_at,
                        CASE 
                            WHEN l.item_id IS NOT NULL 
                                 AND l.expires_at > CURRENT_TIMESTAMP 
                                 AND l.locked_by_user_id IS NOT NULL
                                 AND l.locked_by_user_id != %s
                            THEN true 
                            ELSE false 
                        END as is_locked_by_others
                    FROM {items_table} i
                    LEFT JOIN {locks_table} l ON i.item_id = l.item_id
                    WHERE i.pdf_filename = %s
                      AND i.page_number = %s
                    ORDER BY i.item_order
                """, (current_user_id, pdf_filename, page_number))
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ 락 상태 조회 실패: {e}")
            import traceback
            traceback.print_exc()
            return []
