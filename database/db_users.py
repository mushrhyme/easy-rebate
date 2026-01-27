"""
사용자 관리 Mixin

사용자 및 세션 관련 데이터베이스 작업을 담당합니다.
"""
from typing import Dict, Any, List, Optional
from psycopg2.extras import RealDictCursor


class UsersMixin:
    """사용자 관리 Mixin"""
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        사용자명으로 사용자 정보 조회

        Args:
            username: 사용자명

        Returns:
            사용자 정보 딕셔너리 또는 None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT user_id, username, display_name, is_active,
                           created_at, last_login_at, login_count, created_by_user_id
                    FROM users
                    WHERE username = %s AND is_active = TRUE
                """, (username,))

                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            print(f"⚠️ 사용자 조회 실패: {e}")
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        사용자 ID로 사용자 정보 조회

        Args:
            user_id: 사용자 ID

        Returns:
            사용자 정보 딕셔너리 또는 None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT user_id, username, display_name, is_active,
                           created_at, last_login_at, login_count, created_by_user_id
                    FROM users
                    WHERE user_id = %s
                """, (user_id,))

                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            print(f"⚠️ 사용자 조회 실패: {e}")
            return None

    def update_user_login_info(self, user_id: int) -> bool:
        """
        사용자 로그인 정보 업데이트

        Args:
            user_id: 사용자 ID

        Returns:
            업데이트 성공 여부
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users
                    SET last_login_at = CURRENT_TIMESTAMP,
                        login_count = login_count + 1
                    WHERE user_id = %s
                """, (user_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ 사용자 로그인 정보 업데이트 실패: {e}")
            return False

    def create_user_session(self, user_id: int, session_id: str, ip_address: str = None, user_agent: str = None) -> bool:
        """
        사용자 세션 생성

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
            ip_address: IP 주소 (선택)
            user_agent: 사용자 에이전트 (선택)

        Returns:
            세션 생성 성공 여부
        """
        try:
            print(f"🔵 [create_user_session] 시작: user_id={user_id}, session_id={session_id[:20] if session_id else 'None'}...")
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 먼저 기존 세션이 있는지 확인
                cursor.execute("""
                    SELECT session_id FROM user_sessions WHERE session_id = %s
                """, (session_id,))
                existing = cursor.fetchone()
                if existing:
                    print(f"🔵 [create_user_session] 기존 세션 발견, 업데이트: session_id={session_id[:20]}...")
                
                cursor.execute("""
                    INSERT INTO user_sessions (session_id, user_id, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        ip_address = EXCLUDED.ip_address,
                        user_agent = EXCLUDED.user_agent,
                        created_at = CURRENT_TIMESTAMP,
                        expires_at = CURRENT_TIMESTAMP + INTERVAL '24 hours'
                """, (session_id, user_id, ip_address, user_agent))
                
                rows_affected = cursor.rowcount
                print(f"🔵 [create_user_session] INSERT/UPDATE 완료: rows_affected={rows_affected}")
                
                # 명시적으로 커밋
                conn.commit()
                print(f"🔵 [create_user_session] 커밋 완료")
                
                # 세션이 제대로 생성되었는지 확인 (같은 연결에서)
                cursor.execute("""
                    SELECT session_id, user_id, expires_at, created_at 
                    FROM user_sessions 
                    WHERE session_id = %s
                """, (session_id,))
                result = cursor.fetchone()
                if result:
                    print(f"✅ [create_user_session] 세션 생성 성공: session_id={session_id[:20]}..., user_id={result[1]}, expires_at={result[2]}, created_at={result[3]}")
                    return True
                else:
                    print(f"❌ [create_user_session] 세션 생성 후 확인 실패: session_id={session_id[:20]}... (같은 연결에서도 조회 불가)")
                    return False
        except Exception as e:
            print(f"⚠️ 세션 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_session_user(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        세션 ID로 사용자 정보 조회

        Args:
            session_id: 세션 ID

        Returns:
            사용자 정보 딕셔너리 또는 None
        """
        try:
            print(f"🔵 [get_session_user] 조회 시도: session_id={session_id[:20] if session_id else 'None'}...")
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 먼저 세션 존재 여부 확인 (조건 없이)
                cursor.execute("""
                    SELECT s.session_id, s.user_id, s.created_at, s.expires_at,
                           u.is_active, u.username
                    FROM user_sessions s
                    LEFT JOIN users u ON s.user_id = u.user_id
                    WHERE s.session_id = %s
                """, (session_id,))
                session_raw = cursor.fetchone()
                
                if not session_raw:
                    print(f"⚠️ [get_session_user] 세션이 데이터베이스에 없음: session_id={session_id[:20] if session_id else 'None'}...")
                    # 디버깅: 전체 세션 목록 확인
                    cursor.execute("SELECT COUNT(*) as count FROM user_sessions")
                    total_sessions = cursor.fetchone()
                    print(f"🔵 [get_session_user] 현재 데이터베이스의 총 세션 수: {total_sessions['count'] if total_sessions else 0}")
                    return None
                
                session_data = dict(session_raw)
                print(f"🔵 [get_session_user] 세션 발견: session_id={session_id[:20]}..., user_id={session_data.get('user_id')}, expires_at={session_data.get('expires_at')}, is_active={session_data.get('is_active')}")
                
                # 만료 시간 확인
                from datetime import datetime
                expires_at = session_data.get('expires_at')
                if expires_at:
                    if isinstance(expires_at, str):
                        # 문자열인 경우 파싱 필요 (실제로는 datetime 객체일 수 있음)
                        pass
                    # 만료 여부는 SQL 쿼리에서 처리
                
                # 전체 조건으로 다시 조회
                cursor.execute("""
                    SELECT u.user_id, u.username, u.display_name, u.is_active,
                           s.session_id, s.created_at as session_created_at, s.expires_at
                    FROM user_sessions s
                    JOIN users u ON s.user_id = u.user_id
                    WHERE s.session_id = %s
                      AND s.expires_at > CURRENT_TIMESTAMP
                      AND u.is_active = TRUE
                """, (session_id,))

                result = cursor.fetchone()
                if not result:
                    # 왜 실패했는지 상세 확인
                    if not session_data.get('is_active'):
                        print(f"❌ [get_session_user] 사용자가 비활성화됨: user_id={session_data.get('user_id')}")
                    else:
                        print(f"❌ [get_session_user] 세션이 만료되었거나 조건 불일치: expires_at={session_data.get('expires_at')}, is_active={session_data.get('is_active')}, CURRENT_TIMESTAMP와 비교 필요")
                
                if result:
                    print(f"✅ [get_session_user] 세션 검증 성공: user_id={dict(result).get('user_id')}")
                
                return dict(result) if result else None
        except Exception as e:
            print(f"⚠️ 세션 사용자 조회 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def delete_user_session(self, session_id: str) -> bool:
        """
        사용자 세션 삭제

        Args:
            session_id: 세션 ID

        Returns:
            세션 삭제 성공 여부
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM user_sessions
                    WHERE session_id = %s
                """, (session_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ 세션 삭제 실패: {e}")
            return False

    def get_all_users(self) -> List[Dict[str, Any]]:
        """
        모든 사용자 목록 조회

        Returns:
            사용자 목록
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT user_id, username, display_name, is_active,
                           created_at, last_login_at, login_count
                    FROM users
                    ORDER BY created_at DESC
                """)

                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ 사용자 목록 조회 실패: {e}")
            return []

    def create_user(self, username: str, display_name: str, created_by_user_id: int = None) -> Optional[int]:
        """
        새 사용자 생성

        Args:
            username: 사용자명
            display_name: 표시 이름
            created_by_user_id: 생성자 사용자 ID (선택)

        Returns:
            생성된 사용자 ID 또는 None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, display_name, created_by_user_id)
                    VALUES (%s, %s, %s)
                    RETURNING user_id
                """, (username, display_name, created_by_user_id))

                result = cursor.fetchone()
                conn.commit()
                return result[0] if result else None
        except Exception as e:
            print(f"⚠️ 사용자 생성 실패: {e}")
            return None

    def update_user(self, user_id: int, display_name: str = None, is_active: bool = None) -> bool:
        """
        사용자 정보 업데이트

        Args:
            user_id: 사용자 ID
            display_name: 표시 이름 (선택)
            is_active: 활성 상태 (선택)

        Returns:
            업데이트 성공 여부
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 업데이트할 필드 구성
                update_fields = []
                params = []

                if display_name is not None:
                    update_fields.append("display_name = %s")
                    params.append(display_name)

                if is_active is not None:
                    update_fields.append("is_active = %s")
                    params.append(is_active)

                if not update_fields:
                    return True  # 업데이트할 필드 없음

                params.append(user_id)

                cursor.execute(f"""
                    UPDATE users
                    SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s
                """, params)

                conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ 사용자 업데이트 실패: {e}")
            return False
