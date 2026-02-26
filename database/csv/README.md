# database/csv — CSV 데이터 파일

애플리케이션에서 참조하는 CSV 파일을 모아 둔 폴더입니다. DB 테이블이 아닌 파일 기반 마스터/시드 데이터용입니다.

| 파일 | 용도 |
|------|------|
| `retail_user.csv` | 담당자–소매처 매핑 (소매처코드, 소매처명, 담당자ID, 담당자명, ID). 검색/필터·관리 탭에서 사용 |
| `dist_retail.csv` | 판매처–소매처 매핑 (판매처코드, 판매처명, 소매처코드, 소매처명, 담당자ID, 담당자명) |
| `unit_price.csv` | 단가 명단 (제품명·용량 유사도 매칭용) |
| `users_import.csv` | 사용자 시드 (로그인ID.xlsx → 8열 CSV). `init_database.sql` 실행 시 `\copy`로 `users` 테이블에 반영 |
