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
                try:
                    # 新スキーマ: display_name_ja, password_hash, force_password_change
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               display_name_ja,
                               is_active,
                               password_hash,
                               force_password_change,
                               created_at,
                               last_login_at,
                               login_count,
                               created_by_user_id
                        FROM users
                        WHERE username = %s AND is_active = TRUE
                    """, (username,))
                except Exception:
                    # 旧スキーマ互換
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               NULL::VARCHAR(200) AS display_name_ja,
                               is_active,
                               NULL::VARCHAR(255) AS password_hash,
                               COALESCE(force_password_change, TRUE) AS force_password_change,
                               created_at,
                               last_login_at,
                               login_count,
                               created_by_user_id
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
                try:
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               display_name_ja,
                               is_active,
                               password_hash,
                               force_password_change,
                               created_at,
                               last_login_at,
                               login_count,
                               created_by_user_id
                        FROM users
                        WHERE user_id = %s
                    """, (user_id,))
                except Exception:
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               NULL::VARCHAR(200) AS display_name_ja,
                               is_active,
                               NULL::VARCHAR(255) AS password_hash,
                               COALESCE(force_password_change, TRUE) AS force_password_change,
                               created_at,
                               last_login_at,
                               login_count,
                               created_by_user_id
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
                
                conn.commit()

                # 세션이 제대로 생성되었는지 확인 (같은 연결에서)
                cursor.execute("""
                    SELECT session_id, user_id, expires_at, created_at 
                    FROM user_sessions 
                    WHERE session_id = %s
                """, (session_id,))
                result = cursor.fetchone()
                if result:
                    return True
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
                    return None

                # 전체 조건으로 다시 조회 (만료·활성 여부는 쿼리에서 처리)
                try:
                    cursor.execute("""
                        SELECT u.user_id,
                               u.username,
                               u.display_name,
                               u.display_name_ja,
                               u.is_active,
                               u.password_hash,
                               COALESCE(u.force_password_change, TRUE) AS force_password_change,
                               s.session_id,
                               s.created_at as session_created_at,
                               s.expires_at
                        FROM user_sessions s
                        JOIN users u ON s.user_id = u.user_id
                        WHERE s.session_id = %s
                          AND s.expires_at > CURRENT_TIMESTAMP
                          AND u.is_active = TRUE
                    """, (session_id,))
                except Exception:
                    cursor.execute("""
                        SELECT u.user_id,
                               u.username,
                               u.display_name,
                               NULL::VARCHAR(200) AS display_name_ja,
                               u.is_active,
                               NULL::VARCHAR(255) AS password_hash,
                               COALESCE(u.force_password_change, TRUE) AS force_password_change,
                               s.session_id,
                               s.created_at as session_created_at,
                               s.expires_at
                        FROM user_sessions s
                        JOIN users u ON s.user_id = u.user_id
                        WHERE s.session_id = %s
                          AND s.expires_at > CURRENT_TIMESTAMP
                          AND u.is_active = TRUE
                    """, (session_id,))

                result = cursor.fetchone()
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
                try:
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               display_name_ja,
                               department_ko,
                               department_ja,
                               role,
                               category,
                               is_active,
                               created_at,
                               last_login_at
                        FROM users
                        ORDER BY created_at DESC
                    """)
                except Exception:
                    cursor.execute("""
                        SELECT user_id,
                               username,
                               display_name,
                               NULL::VARCHAR(200) AS display_name_ja,
                               NULL::VARCHAR(200) AS department_ko,
                               NULL::VARCHAR(200) AS department_ja,
                               NULL::VARCHAR(100) AS role,
                               NULL::VARCHAR(100) AS category,
                               is_active,
                               created_at,
                               last_login_at
                        FROM users
                        ORDER BY created_at DESC
                    """)

                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ 사용자 목록 조회 실패: {e}")
            return []

    def create_user(
        self,
        username: str,
        display_name: str,
        display_name_ja: str | None = None,
        department_ko: str | None = None,
        department_ja: str | None = None,
        role: str | None = None,
        category: str | None = None,
        created_by_user_id: int | None = None,
        password_hash: str | None = None,
    ) -> Optional[int]:
        """새 사용자 생성. password_hash가 없으면 초기 비밀번호(ID와 동일)로 설정하려면 호출측에서 hash(username) 전달."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO users (username, display_name, display_name_ja, department_ko, department_ja, role, category, created_by_user_id, password_hash, force_password_change)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING user_id
                    """, (username, display_name, display_name_ja, department_ko or None, department_ja or None, role or None, category or None, created_by_user_id, password_hash))
                except Exception:
                    cursor.execute("""
                        INSERT INTO users (username, display_name, display_name_ja, created_by_user_id, password_hash, force_password_change)
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        RETURNING user_id
                    """, (username, display_name, display_name_ja, created_by_user_id, password_hash))

                result = cursor.fetchone()
                conn.commit()
                return result[0] if result else None
        except Exception as e:
            print(f"⚠️ 사용자 생성 실패: {e}")
            return None

    def update_user(
        self,
        user_id: int,
        display_name: str | None = None,
        display_name_ja: str | None = None,
        department_ko: str | None = None,
        department_ja: str | None = None,
        role: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> bool:
        """사용자 정보 업데이트"""
        try:
            from typing import Any

            with self.get_connection() as conn:
                cursor = conn.cursor()

                update_fields: list[str] = []
                params: list[Any] = []

                if display_name is not None:
                    update_fields.append("display_name = %s")
                    params.append(display_name)
                if display_name_ja is not None:
                    update_fields.append("display_name_ja = %s")
                    params.append(display_name_ja)
                if department_ko is not None:
                    update_fields.append("department_ko = %s")
                    params.append(department_ko or None)
                if department_ja is not None:
                    update_fields.append("department_ja = %s")
                    params.append(department_ja or None)
                if role is not None:
                    update_fields.append("role = %s")
                    params.append(role or None)
                if category is not None:
                    update_fields.append("category = %s")
                    params.append(category or None)
                if is_active is not None:
                    update_fields.append("is_active = %s")
                    params.append(is_active)

                if not update_fields:
                    return True

                params.append(user_id)

                try:
                    cursor.execute(f"""
                        UPDATE users SET {', '.join(update_fields)}
                        WHERE user_id = %s
                    """, params)
                except Exception:
                    fields_wo_extra = [f for f in update_fields if f.startswith(("display_name", "is_active"))]
                    if not fields_wo_extra:
                        return True
                    cursor.execute(f"""
                        UPDATE users SET {', '.join(fields_wo_extra)}
                        WHERE user_id = %s
                    """, params)

                conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ 사용자 업데이트 실패: {e}")
            return False

    def update_password(self, user_id: int, password_hash: str) -> bool:
        """비밀번호 변경 (해시 저장 후 강제 변경 플래그 해제)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        UPDATE users
                        SET password_hash = %s, force_password_change = FALSE
                        WHERE user_id = %s
                    """, (password_hash, user_id))
                except Exception:
                    cursor.execute("""
                        UPDATE users
                        SET force_password_change = FALSE
                        WHERE user_id = %s
                    """, (user_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"⚠️ 비밀번호 업데이트 실패: {e}")
            return False


