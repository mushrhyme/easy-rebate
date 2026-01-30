"""
로그인ID.xlsx에서 사용자 목록을 읽어 users 테이블에 INSERT/UPDATE 합니다.

- B열: username (로그인 ID)
- D열: display_name (표시 이름)

실행: 프로젝트 루트에서
  python -m database.sync_users_from_excel
  또는
  python database/sync_users_from_excel.py
"""
from pathlib import Path

# 프로젝트 루트를 path에 넣어서 import 및 엑셀 경로 해결
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv(_PROJECT_ROOT / ".env")
    except Exception:
        pass


def main():
    _load_dotenv()

    try:
        import openpyxl
    except ImportError:
        print("openpyxl이 필요합니다: pip install openpyxl")
        return 1

    from database.registry import get_db

    excel_path = _PROJECT_ROOT / "로그인ID.xlsx"
    if not excel_path.exists():
        print(f"엑셀 파일을 찾을 수 없습니다: {excel_path}")
        return 1

    wb = openpyxl.load_workbook(excel_path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, max_col=4, values_only=True))
    wb.close()

    db = get_db()
    processed = 0
    skipped = 0

    with db.get_connection() as conn:
        cursor = conn.cursor()
        for row in rows:
            b = row[1] if len(row) > 1 else None
            d = row[3] if len(row) > 3 else None
            if b is None or (isinstance(b, str) and not b.strip()):
                skipped += 1
                continue
            username = str(b).strip()
            display_name = str(d).strip() if d is not None else username

            cursor.execute(
                """
                INSERT INTO users (username, display_name, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (username) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    is_active = TRUE
                """,
                (username, display_name),
            )
            processed += 1
        conn.commit()

    print(f"완료: 사용자 {processed}건 반영 (건너뜀 {skipped}건)")
    return 0


if __name__ == "__main__":
    exit(main())
