#!/usr/bin/env python3
"""SAP 대상 문서 진단: DB 직접 조회 (check-document API와 동일 로직)"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PDF = "三菱食品東日本_2025.01 (2)-1-4.pdf"

def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "rebate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT pdf_filename, created_by_user_id, data_year, data_month, form_type FROM documents_current WHERE pdf_filename = %s",
            (PDF,),
        )
        row = cur.fetchone()
        if not row:
            print("documents_current에 없음. (아카이브에 있거나 미등록)")
            return
        print("pdf_filename:", row["pdf_filename"])
        print("created_by_user_id:", row["created_by_user_id"])
        print("data_year:", row["data_year"], "data_month:", row["data_month"])
        print("form_type:", row["form_type"])

        cur.execute(
            "SELECT 1 FROM page_data_current WHERE pdf_filename = %s AND page_role = 'detail' LIMIT 1",
            (PDF,),
        )
        has_detail = cur.fetchone() is not None
        print("has_detail_page:", has_detail)

        reasons = []
        if row["created_by_user_id"] is None:
            reasons.append("created_by_user_id가 NULL")
        if row["data_year"] is None or row["data_month"] is None:
            reasons.append("data_year 또는 data_month가 NULL")
        if not has_detail:
            reasons.append("detail 페이지 없음")
        if reasons:
            print("reason:", "; ".join(reasons))
        else:
            print("reason: 조건 만족. 연월 선택이", row["data_year"], "年", row["data_month"], "月 인지 확인하세요.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
