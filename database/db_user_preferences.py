"""
사용자 UI 설정 (검토 그리드 컬럼 순서 등)
"""
from typing import List, Optional

from psycopg2.extras import Json


def _safe_log(msg: str, e: Exception = None) -> None:
    part = f": {type(e).__name__}" if e else ""
    print(f"[db_user_preferences] {msg}{part}", flush=True)


class UserPreferencesMixin:
    """user_preferences 테이블 — user_id당 1행"""

    def _ensure_user_preferences_table(self, cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                review_grid_column_order JSONB,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def get_review_grid_column_order(self, user_id: int) -> Optional[List[str]]:
        """
        검토 탭 그리드 비동결 컬럼 키 순서.
        Returns: 예 ['得意先', '金額', ...] 또는 없으면 None
        """
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                self._ensure_user_preferences_table(cur)
                cur.execute(
                    "SELECT review_grid_column_order FROM user_preferences WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    return None
                val = row[0]
                if isinstance(val, str):
                    import json

                    val = json.loads(val)
                if not isinstance(val, list):
                    return None
                return [str(x) for x in val]
        except Exception as e:
            _safe_log("get_review_grid_column_order failed", e)
            return None

    def set_review_grid_column_order(self, user_id: int, keys: List[str]) -> bool:
        """순서 전체를 upsert"""
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                self._ensure_user_preferences_table(cur)
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, review_grid_column_order, updated_at)
                    VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        review_grid_column_order = EXCLUDED.review_grid_column_order,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, Json(keys)),
                )
                return True
        except Exception as e:
            _safe_log("set_review_grid_column_order failed", e)
            return False
