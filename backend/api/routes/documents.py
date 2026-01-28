"""
문서 업로드 및 관리 API
"""
import asyncio
import re
import json
import time
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.registry import get_db
from database.table_selector import get_table_name, get_table_suffix
from modules.core.processor import PdfProcessor
from modules.utils.config import rag_config
from backend.core.session import SessionManager
from backend.core.config import settings
from backend.core.auth import get_current_user_id
from backend.api.routes.websocket import manager

router = APIRouter()


def query_documents_table(
    db,
    form_type: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None
) -> List[Tuple]:
    """
    documents 테이블 조회 헬퍼 함수 (current/archive 테이블 자동 선택)
    
    Args:
        db: 데이터베이스 인스턴스
        form_type: 양식지 타입 필터 (선택사항)
        year: 연도 (선택사항, 없으면 current + archive 모두 조회)
        month: 월 (선택사항, 없으면 current + archive 모두 조회)
    
    Returns:
        조회된 행 리스트
    """
    query_start = time.perf_counter()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 연월이 지정되면 해당 테이블만 조회
        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            documents_table = f"documents_{table_suffix}"
            
            if form_type:
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM {documents_table}
                    WHERE form_type = %s
                    ORDER BY created_at DESC
                """, (form_type,))
            else:
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM {documents_table}
                    ORDER BY created_at DESC
                """)
            rows = cursor.fetchall()
            query_label = f"documents_{table_suffix}" + (f" (form_type={form_type})" if form_type else " (전체)")
        else:
            # current + archive 모두 조회
            if form_type:
                cursor.execute("""
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM documents_current
                    WHERE form_type = %s
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM documents_archive
                    WHERE form_type = %s
                    ORDER BY created_at DESC
                """, (form_type, form_type))
            else:
                cursor.execute("""
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM documents_current
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, created_at, data_year, data_month
                    FROM documents_archive
                    ORDER BY created_at DESC
                """)
            rows = cursor.fetchall()
            query_label = "documents (current+archive)" + (f" (form_type={form_type})" if form_type else " (전체)")
    
    query_time = time.perf_counter() - query_start
    print(f"⏱️ [DB 성능] documents 테이블 조회 ({query_label}): {query_time:.3f}초, {len(rows)}개 행")
    
    return rows


def query_page_meta_batch(
    db,
    pdf_filenames: List[str],
    year: Optional[int] = None,
    month: Optional[int] = None
) -> List[Tuple]:
    """
    page_data 테이블에서 page_meta 배치 조회 헬퍼 함수
    
    Args:
        db: 데이터베이스 인스턴스
        pdf_filenames: PDF 파일명 리스트
        year: 연도 (선택사항, 없으면 current + archive 모두 조회)
        month: 월 (선택사항, 없으면 current + archive 모두 조회)
    
    Returns:
        (pdf_filename, page_meta) 튜플 리스트
    """
    if not pdf_filenames:
        return []
    
    query_start = time.perf_counter()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 연월이 지정되면 해당 테이블만 조회
        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            page_data_table = f"page_data_{table_suffix}"
            cursor.execute(f"""
                SELECT pdf_filename, page_meta
                FROM {page_data_table}
                WHERE pdf_filename = ANY(%s) AND page_number = 1
            """, (pdf_filenames,))
        else:
            # current + archive 모두 조회
            cursor.execute("""
                SELECT pdf_filename, page_meta
                FROM page_data_current
                WHERE pdf_filename = ANY(%s) AND page_number = 1
                UNION ALL
                SELECT pdf_filename, page_meta
                FROM page_data_archive
                WHERE pdf_filename = ANY(%s) AND page_number = 1
            """, (pdf_filenames, pdf_filenames))
        
        page_meta_rows = cursor.fetchall()
    
    query_time = time.perf_counter() - query_start
    print(f"⏱️ [DB 성능] page_data 테이블 조회 (page_meta): {query_time:.3f}초, {len(page_meta_rows)}개 행")
    
    return page_meta_rows


def extract_year_month_from_billing_date(billing_date_str: str) -> Optional[Tuple[int, int]]:
    """
    請求年月 문자열에서 연월 추출
    
    Args:
        billing_date_str: "2025年02月" 또는 "2025年02月分" 형식의 문자열
    
    Returns:
        (year, month) 튜플 또는 None
    """
    if not billing_date_str:
        return None
    
    # "2025年02月" 또는 "2025年02月分" 형식 파싱
    # 한자 숫자도 처리: "２０２５年０２月"
    patterns = [
        r'(\d{4})年(\d{1,2})月',  # "2025年02月"
        r'([０-９]{4})年([０-９]{1,2})月',  # "２０２５年０２月" (전각 숫자)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, billing_date_str)
        if match:
            year_str = match.group(1)
            month_str = match.group(2)
            
            # 전각 숫자를 반각으로 변환
            if year_str[0] == '０':
                year_str = year_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                month_str = month_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            
            try:
                year = int(year_str)
                month = int(month_str)
                if 1 <= month <= 12:
                    return (year, month)
            except ValueError:
                continue
    
    return None


def get_document_year_month(db, pdf_filename: str, year: Optional[int] = None, month: Optional[int] = None) -> Optional[Tuple[int, int]]:
    """
    문서의 첫 번째 페이지에서 請求年月 추출
    
    Args:
        db: 데이터베이스 인스턴스
        pdf_filename: PDF 파일명
        year: 연도 (선택사항, 테이블 선택용)
        month: 월 (선택사항, 테이블 선택용)
    
    Returns:
        (year, month) 튜플 또는 None
    """
    try:
        # 연월에 따라 테이블 선택
        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            page_data_table = f"page_data_{table_suffix}"
        else:
            # current에서 먼저 찾고, 없으면 archive에서 찾기
            page_data_table = "page_data_current"
        
        # 첫 번째 페이지의 page_meta 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT page_meta
                FROM {page_data_table}
                WHERE pdf_filename = %s AND page_number = 1
            """, (pdf_filename,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                print(f"⚠️ {pdf_filename}: 첫 페이지의 page_meta가 없음")
                return None
            
            # page_meta가 JSONB이므로 파싱
            page_meta = row[0]
            if isinstance(page_meta, str):
                page_meta = json.loads(page_meta)
            
            # page_meta의 구조 확인 (디버깅)
            print(f"🔍 {pdf_filename}: page_meta 키들 = {list(page_meta.keys()) if isinstance(page_meta, dict) else 'not dict'}")
            
            # document_meta에서 請求年月 찾기
            document_meta = page_meta.get('document_meta', {})
            if isinstance(document_meta, str):
                document_meta = json.loads(document_meta)
            
            if not isinstance(document_meta, dict):
                print(f"⚠️ {pdf_filename}: document_meta가 dict가 아님: {type(document_meta)}")
                # page_meta 자체에서 직접 찾기 시도
                billing_date = page_meta.get('請求年月')
                if billing_date:
                    print(f"✅ {pdf_filename}: page_meta에서 직접 請求年月 발견: {billing_date}")
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
            else:
                print(f"🔍 {pdf_filename}: document_meta 키들 = {list(document_meta.keys())}")
                billing_date = document_meta.get('請求年月')
                if billing_date:
                    print(f"✅ {pdf_filename}: document_meta에서 請求年月 발견: {billing_date}")
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
                
                # 다른 가능한 필드명도 확인
                for key in ['請求年月分', '請求期間', '対象期間']:
                    if key in document_meta:
                        value = document_meta[key]
                        print(f"✅ {pdf_filename}: document_meta에서 {key} 발견: {value}")
                        if isinstance(value, str):
                            result = extract_year_month_from_billing_date(value)
                            if result:
                                return result
            
            print(f"⚠️ {pdf_filename}: 請求年月를 찾을 수 없음")
            
    except Exception as e:
        print(f"⚠️ {pdf_filename}의 연월 추출 실패: {e}")
        import traceback
        traceback.print_exc()
    
    return None


class DocumentResponse(BaseModel):
    """문서 응답 모델"""
    pdf_filename: str
    total_pages: int
    form_type: Optional[str] = None
    status: str
    created_at: Optional[str] = None  # 업로드 날짜 (ISO 형식)
    data_year: Optional[int] = None  # 문서 데이터 연도 (請求年月에서 추출)
    data_month: Optional[int] = None  # 문서 데이터 월 (請求年月에서 추출)


class DocumentListResponse(BaseModel):
    """문서 목록 응답 모델"""
    documents: List[DocumentResponse]
    total: int


@router.post("/upload", response_model=dict)
async def upload_documents(
    form_type: str = Form(...),
    files: List[UploadFile] = File(...),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    background_tasks: BackgroundTasks = None,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    PDF 파일 업로드 및 처리
    
    Args:
        form_type: 양식지 타입 ("01"~"05")
        files: 업로드된 PDF 파일 리스트
        year: 연도 (선택사항)
        month: 월 (선택사항, 1-12)
        background_tasks: 백그라운드 작업
        db: 데이터베이스 인스턴스
    """
    if form_type not in ["01", "02", "03", "04", "05"]:
        raise HTTPException(status_code=400, detail="Invalid form_type. Must be 01-05")
    
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    # month 유효성 검사
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail=f"Invalid month: {month}. Must be 1-12")
    
    # 세션 ID 생성 (임시로 파일명 기반)
    session_id = SessionManager.generate_session_id()
    
    results = []
    for uploaded_file in files:
        try:
            # 파일명에서 확장자 제거
            pdf_name = Path(uploaded_file.filename).stem
            
            # 파일 크기 확인
            file_bytes = await uploaded_file.read()
            if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "error",
                    "error": f"File size exceeds {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
                })
                continue
            
            # 파일이 이미 존재하는지 확인
            pdf_filename = f"{pdf_name}.pdf"
            doc_info = db.check_document_exists(pdf_filename)
            
            if doc_info['exists']:
                # form_type 업데이트 (null인 경우) - current와 archive 모두 업데이트
                if doc_info.get('form_type') is None:
                    try:
                        with db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE documents_current 
                                SET form_type = %s 
                                WHERE pdf_filename = %s
                            """, (form_type, pdf_filename))
                            cursor.execute("""
                                UPDATE documents_archive 
                                SET form_type = %s 
                                WHERE pdf_filename = %s
                            """, (form_type, pdf_filename))
                            conn.commit()
                    except Exception:
                        pass
                
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "exists",
                    "pages": doc_info.get('total_pages', 0)
                })
            else:
                # 새 파일: 처리 대기 상태로 추가
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "pending",
                    "pdf_name": pdf_name
                })
                
                # 백그라운드에서 처리 시작
                if background_tasks:
                    background_tasks.add_task(
                        process_pdf_background,
                        file_bytes=file_bytes,
                        pdf_name=pdf_name,
                        form_type=form_type,
                        session_id=session_id,
                        user_id=current_user_id,
                        data_year=year,
                        data_month=month
                    )
        
        except Exception as e:
            results.append({
                "filename": uploaded_file.filename,
                "status": "error",
                "error": str(e)
            })
    
    return {
        "message": "Files uploaded",
        "results": results,
        "session_id": session_id
    }


async def process_pdf_background(
    file_bytes: bytes,
    pdf_name: str,
    form_type: str,
    session_id: str,
    user_id: int,
    data_year: Optional[int] = None,
    data_month: Optional[int] = None
):
    """
    백그라운드에서 PDF 처리
    
    Args:
        file_bytes: PDF 파일 바이트 데이터
        pdf_name: PDF 파일명 (확장자 제외)
        form_type: 양식지 타입
        session_id: 세션 ID (WebSocket task_id로 사용)
    """
    pdf_path = None
    try:
        # 이벤트 루프 캡처 (스레드에서 안전하게 사용하기 위해)
        main_loop = asyncio.get_event_loop()
        
        # 진행률 전송 함수 정의 (스레드 안전)
        def progress_callback(page_num: int, total_pages: int, message: str):
            """진행률 콜백 - WebSocket으로 전송 (스레드 안전)"""
            progress_data = {
                "type": "progress",
                "file_name": f"{pdf_name}.pdf",
                "current_page": page_num,
                "total_pages": total_pages,
                "message": message,
                "progress": page_num / total_pages if total_pages > 0 else 0
            }
            # 메인 이벤트 루프에서 비동기 함수 실행 (스레드 안전)
            asyncio.run_coroutine_threadsafe(
                manager.send_progress(session_id, progress_data),
                main_loop
            )
        
        # 시작 메시지 전송
        await manager.send_progress(session_id, {
            "type": "start",
            "file_name": f"{pdf_name}.pdf",
            "message": f"Processing {pdf_name}.pdf..."
        })
        
        # 임시 파일로 저장
        pdf_path = SessionManager.save_pdf_file_from_bytes(
            file_bytes=file_bytes,
            pdf_name=pdf_name,
            session_id=session_id
        )
        
        # PDF 처리 (동기 함수를 비동기로 실행)
        success, pages, error_msg, elapsed_time = await main_loop.run_in_executor(
            None,
            lambda: PdfProcessor.process_pdf(
                pdf_name=pdf_name,
                pdf_path=str(pdf_path),
                dpi=rag_config.dpi,
                progress_callback=progress_callback,
                form_type=form_type,
                user_id=user_id,
                data_year=data_year,
                data_month=data_month
            )
        )
        
        if success:
            # form_type 및 지정한 년월 업데이트
            pdf_filename = f"{pdf_name}.pdf"
            try:
                from database.registry import get_db
                from datetime import datetime
                db = get_db()
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    # 지정한 년월이 있으면 created_at을 해당 년월 1일로 설정
                    if data_year and data_month:
                        created_at = datetime(data_year, data_month, 1)
                        cursor.execute("""
                            UPDATE documents_current 
                            SET form_type = %s, created_at = %s, data_year = %s, data_month = %s
                            WHERE pdf_filename = %s
                        """, (form_type, created_at, data_year, data_month, pdf_filename))
                    else:
                        cursor.execute("""
                            UPDATE documents_current 
                            SET form_type = %s 
                            WHERE pdf_filename = %s
                        """, (form_type, pdf_filename))
                    conn.commit()
            except Exception:
                pass
            
            # 완료 메시지 전송
            await manager.send_progress(session_id, {
                "type": "complete",
                "file_name": f"{pdf_name}.pdf",
                "pages": pages,
                "elapsed_time": elapsed_time,
                "message": f"Processing completed: {pages} pages in {elapsed_time:.1f}s"
            })
        else:
            # 실패 메시지 전송
            await manager.send_progress(session_id, {
                "type": "error",
                "file_name": f"{pdf_name}.pdf",
                "error": error_msg,
                "message": f"Processing failed: {error_msg}"
            })
    
    except Exception as e:
        print(f"❌ PDF 처리 실패: {pdf_name}, 오류: {e}")
        import traceback
        traceback.print_exc()
        try:
            await manager.send_progress(session_id, {
                "type": "error",
                "file_name": f"{pdf_name}.pdf",
                "error": str(e),
                "message": f"Processing failed: {str(e)}"
            })
        except Exception as ws_error:
            print(f"⚠️ WebSocket 메시지 전송 실패: {ws_error}")
    finally:
        # 처리 완료 후 temp 폴더의 PDF 파일 및 세션 디렉토리 정리
        # 이미지로 변환되어 static 폴더에 저장되므로 temp 폴더의 파일은 더 이상 필요 없음
        try:
            if pdf_path and pdf_path.exists():
                pdf_path.unlink()
                print(f"🗑️ [temp 정리] PDF 파일 삭제: {pdf_path}")
            
            # 세션 디렉토리 내 모든 파일 정리
            if pdf_path:
                pdfs_dir = pdf_path.parent  # temp/{session_id}/pdfs
                session_dir = pdfs_dir.parent  # temp/{session_id}
                
                # pdfs 디렉토리 내 모든 파일 삭제
                if pdfs_dir.exists():
                    for file in pdfs_dir.iterdir():
                        if file.is_file():
                            file.unlink()
                            print(f"🗑️ [temp 정리] 파일 삭제: {file}")
                    # pdfs 디렉토리가 비어있으면 삭제
                    if not any(pdfs_dir.iterdir()):
                        pdfs_dir.rmdir()
                        print(f"🗑️ [temp 정리] pdfs 디렉토리 삭제: {pdfs_dir}")
                
                # 세션 디렉토리 내 다른 파일들도 정리 (OCR 결과 JSON 등)
                if session_dir.exists():
                    for item in session_dir.iterdir():
                        if item.is_file():
                            item.unlink()
                            print(f"🗑️ [temp 정리] 파일 삭제: {item}")
                    # 세션 디렉토리가 비어있으면 삭제
                    if not any(session_dir.iterdir()):
                        session_dir.rmdir()
                        print(f"🗑️ [temp 정리] 세션 디렉토리 삭제: {session_dir}")
        except Exception as cleanup_error:
            # 정리 실패해도 처리 흐름에는 영향 없음
            print(f"⚠️ [temp 정리] 실패 (무시): {cleanup_error}")


@router.get("/", response_model=DocumentListResponse)
async def get_documents(
    form_type: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db=Depends(get_db)
):
    """
    문서 목록 조회 (current/archive 테이블 사용)
    
    Args:
        form_type: 양식지 타입 필터 (선택사항)
        year: 연도 (선택사항, 없으면 current + archive 모두 조회)
        month: 월 (선택사항, 없으면 current + archive 모두 조회)
        db: 데이터베이스 인스턴스
    """
    total_start = time.perf_counter()  # 전체 엔드포인트 시간 측정 시작
    
    try:
        # documents 테이블 조회 (헬퍼 함수 사용)
        rows = query_documents_table(db, form_type=form_type, year=year, month=month)
        
        # 배치로 첫 페이지의 page_meta 일괄 조회 (N+1 쿼리 문제 해결)
        pdf_filenames = [row[0] for row in rows]
        page_meta_rows = query_page_meta_batch(db, pdf_filenames, year=year, month=month)
        
        # 데이터 처리 시간 측정
        processing_start = time.perf_counter()
        documents = []
        for row in rows:
            pdf_filename = row[0]
            total_pages = row[1]
            form_type = row[2]
            created_at = row[3]
            data_year = row[4] if len(row) > 4 else None
            data_month = row[5] if len(row) > 5 else None
            
            # created_at을 ISO 형식 문자열로 변환
            created_at_str = None
            if created_at:
                if isinstance(created_at, str):
                    created_at_str = created_at
                elif isinstance(created_at, datetime):
                    created_at_str = created_at.isoformat()
                else:
                    try:
                        created_at_str = str(created_at)
                    except Exception as e:
                        print(f"⚠️ created_at 변환 실패: {pdf_filename}, 타입: {type(created_at)}, 값: {created_at}, 오류: {e}")
                        created_at_str = None
            
            # data_year, data_month가 없으면 page_meta에서 추출 시도
            if not data_year or not data_month:
                for page_filename, page_meta_data in page_meta_rows:
                    if page_filename == pdf_filename and page_meta_data:
                        try:
                            if isinstance(page_meta_data, str):
                                page_meta = json.loads(page_meta_data)
                            else:
                                page_meta = page_meta_data
                            
                            document_meta = page_meta.get('document_meta', {})
                            if isinstance(document_meta, str):
                                document_meta = json.loads(document_meta)
                            
                            billing_date = None
                            if isinstance(document_meta, dict):
                                billing_date = document_meta.get('請求年月')
                            else:
                                billing_date = page_meta.get('請求年月')
                            
                            if billing_date:
                                year_month = extract_year_month_from_billing_date(billing_date)
                                if year_month:
                                    data_year = data_year or year_month[0]
                                    data_month = data_month or year_month[1]
                                    break
                        except Exception as e:
                            print(f"⚠️ {pdf_filename}의 請求年月 추출 실패: {e}")
            
            documents.append(DocumentResponse(
                pdf_filename=pdf_filename,
                total_pages=total_pages,
                form_type=form_type,
                status="completed",
                created_at=created_at_str,
                data_year=data_year,
                data_month=data_month
            ))
        processing_time = time.perf_counter() - processing_start
        print(f"⏱️ [DB 성능] 데이터 처리 시간: {processing_time:.3f}초, {len(documents)}개 문서")
        
        total_time = time.perf_counter() - total_start  # 전체 엔드포인트 시간 측정 종료
        print(f"⏱️ [DB 성능] 전체 엔드포인트 시간: {total_time:.3f}초")
        
        return DocumentListResponse(
            documents=documents,
            total=len(documents)
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}")
async def get_document(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    특정 문서 정보 조회
    
    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        doc = db.get_document(pdf_filename)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # created_at을 ISO 형식 문자열로 변환
        created_at_str = None
        if doc.get('created_at'):
            created_at = doc['created_at']
            if isinstance(created_at, str):
                created_at_str = created_at
            elif isinstance(created_at, datetime):
                # datetime 객체인 경우 ISO 형식으로 변환
                created_at_str = created_at.isoformat()
            else:
                # 다른 타입인 경우 문자열로 변환 시도
                try:
                    created_at_str = str(created_at)
                except Exception as e:
                    print(f"⚠️ created_at 변환 실패: {doc.get('pdf_filename')}, 타입: {type(created_at)}, 값: {created_at}, 오류: {e}")
                    created_at_str = None
        
        # 문서의 첫 번째 페이지에서 請求年月 추출
        year_month = get_document_year_month(db, pdf_filename)
        data_year = year_month[0] if year_month else None
        data_month = year_month[1] if year_month else None
        
        return DocumentResponse(
            pdf_filename=doc['pdf_filename'],
            total_pages=doc['total_pages'],
            form_type=doc.get('form_type'),
            status="completed",
            created_at=created_at_str,
            data_year=data_year,
            data_month=data_month
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{pdf_filename}")
async def delete_document(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서 삭제
    
    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 문서 삭제 (current와 archive 모두에서 삭제)
            cursor.execute("""
                DELETE FROM documents_current 
                WHERE pdf_filename = %s
            """, (pdf_filename,))
            deleted_count = cursor.rowcount
            
            cursor.execute("""
                DELETE FROM documents_archive 
                WHERE pdf_filename = %s
            """, (pdf_filename,))
            deleted_count += cursor.rowcount
            
            if deleted_count == 0:
                raise HTTPException(status_code=404, detail="Document not found")
            
            conn.commit()
        
        return {"message": "Document deleted successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages")
async def get_document_pages(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서의 페이지 목록 조회
    
    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        page_results = db.get_page_results(pdf_filename)
        
        pages = []
        for page_result in page_results:
            pages.append({
                "page_number": page_result.get('page_number'),
                "items_count": len(page_result.get('items', []))
            })
        
        return {"pages": pages}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages/{page_number}/meta")
async def get_page_meta(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    특정 페이지의 메타데이터 조회 (page_meta)
    
    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        page_result = db.get_page_result(pdf_filename, page_number)
        
        if not page_result:
            raise HTTPException(status_code=404, detail="Page not found")
        
        # page_meta 추출: page_role과 items를 제외한 모든 키가 page_meta
        # get_page_result는 page_meta를 spread해서 최상위 키로 추가하므로,
        # page_role과 items를 제외한 나머지를 page_meta로 구성
        page_role = page_result.get('page_role')
        page_meta = {}
        
        # page_role과 items, page_number를 제외한 모든 키를 page_meta로 구성
        exclude_keys = {'page_role', 'items', 'page_number', 'customer'}
        for key, value in page_result.items():
            if key not in exclude_keys:
                page_meta[key] = value
        
        return {
            "page_role": page_role,
            "page_meta": page_meta
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
