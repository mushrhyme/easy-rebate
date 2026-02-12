"""
문서 업로드 및 관리 API
"""
import asyncio
import base64
import re
import json
import time
from pathlib import Path
from io import BytesIO
from typing import List, Optional, Tuple
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.registry import get_db
from database.table_selector import get_table_name, get_table_suffix
from modules.core.processor import PdfProcessor
from modules.utils.config import rag_config, get_project_root
from backend.core.session import SessionManager
from backend.core.config import settings
from backend.core.auth import get_current_user_id
from backend.api.routes.websocket import manager

router = APIRouter()


def _answer_key_debug_dir(pdf_filename: str) -> Path:
    """정답지 생성 디버깅용: debug/answer_key/{문서명}/ 경로 반환 (폴더는 호출측에서 생성)."""
    stem = Path(pdf_filename).stem
    safe_name = stem.replace("\\", "_").replace("/", "_").strip() or "unknown"
    return get_project_root() / "debug" / "answer_key" / safe_name


def query_documents_table(
    db,
    form_type: Optional[str] = None,
    upload_channel: Optional[str] = None,
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
            
            filter_cond = upload_channel or form_type
            if filter_cond:
                col, val = ("upload_channel", upload_channel) if upload_channel else ("form_type", form_type)
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM {documents_table}
                    WHERE {col} = %s
                    ORDER BY created_at DESC
                """, (val,))
            else:
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM {documents_table}
                    ORDER BY created_at DESC
                """)
            rows = cursor.fetchall()
            query_label = f"documents_{table_suffix}" + (f" (filter={filter_cond})" if filter_cond else " (전체)")
        else:
            # current + archive 모두 조회
            filter_cond = upload_channel or form_type
            col, val = ("upload_channel", upload_channel) if upload_channel else ("form_type", form_type)
            if filter_cond:
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_current
                    WHERE {col} = %s
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_archive
                    WHERE {col} = %s
                    ORDER BY created_at DESC
                """, (val, val))
            else:
                cursor.execute("""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_current
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_archive
                    ORDER BY created_at DESC
                """)
            rows = cursor.fetchall()
            query_label = "documents (current+archive)" + (f" (filter={filter_cond})" if filter_cond else " (전체)")
    
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
                return None
            
            # page_meta가 JSONB이므로 파싱
            page_meta = row[0]
            if isinstance(page_meta, str):
                page_meta = json.loads(page_meta)
            
            # document_meta에서 請求年月 찾기
            document_meta = page_meta.get('document_meta', {})
            if isinstance(document_meta, str):
                document_meta = json.loads(document_meta)
            
            if not isinstance(document_meta, dict):
                # page_meta 자체에서 직접 찾기 시도
                billing_date = page_meta.get('請求年月')
                if billing_date:
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
            else:
                billing_date = document_meta.get('請求年月')
                if billing_date:
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
                
                # 다른 가능한 필드명도 확인
                for key in ['請求年月分', '請求期間', '対象期間']:
                    if key in document_meta:
                        value = document_meta[key]
                        if isinstance(value, str):
                            result = extract_year_month_from_billing_date(value)
                            if result:
                                return result
            
    except Exception:
        pass
    
    return None


class DocumentResponse(BaseModel):
    """문서 응답 모델"""
    pdf_filename: str
    total_pages: int
    form_type: Optional[str] = None
    upload_channel: Optional[str] = None
    status: str
    created_at: Optional[str] = None  # 업로드 날짜 (ISO 형식)
    data_year: Optional[int] = None  # 문서 데이터 연도 (請求年月에서 추출)
    data_month: Optional[int] = None  # 문서 데이터 월 (請求年月에서 추출)
    is_answer_key_document: bool = False  # 정답지 생성 대상 여부 (true면 검토 탭에서 제외)


class DocumentListResponse(BaseModel):
    """문서 목록 응답 모델"""
    documents: List[DocumentResponse]
    total: int


@router.post("/upload", response_model=dict)
async def upload_documents(
    upload_channel: Optional[str] = Form(None, alias="upload_channel"),
    form_type: Optional[str] = Form(None, alias="form_type"),  # 하위 호환 (더 이상 upload_channel 결정에 사용하지 않음)
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
        upload_channel: finet(엑셀) | mail(Upstage OCR)
        form_type: 하위 호환 (01-06, 더 이상 upload_channel 추론에는 사용하지 않음)
        files: 업로드된 PDF 파일 리스트
        year: 연도 (선택사항)
        month: 월 (선택사항, 1-12)
    """
    # 옵션 1: 텍스트 추출 방식은 upload_channel 기준으로만 결정.
    # form_type만으로 channel을 추론하는 것은 지원하지 않는다.
    if not upload_channel or upload_channel not in ("finet", "mail"):
        raise HTTPException(
            status_code=400,
            detail="upload_channel (finet|mail) is required. form_type 파라미터만 보내는 방식은 더 이상 지원하지 않습니다.",
        )
    
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
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE documents_current 
                            SET upload_channel = %s 
                            WHERE pdf_filename = %s
                        """, (upload_channel, pdf_filename))
                        cursor.execute("""
                            UPDATE documents_archive 
                            SET upload_channel = %s 
                            WHERE pdf_filename = %s
                        """, (upload_channel, pdf_filename))
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
                        upload_channel=upload_channel,
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


@router.post("/upload-with-bbox", response_model=dict)
async def upload_documents_with_bbox(
    upload_channel: Optional[str] = Form(None, alias="upload_channel"),
    form_type: Optional[str] = Form(None, alias="form_type"),  # 하위 호환 (더 이상 upload_channel 결정에 사용하지 않음)
    files: List[UploadFile] = File(...),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    background_tasks: BackgroundTasks = None,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    PDF 업로드 후 좌표 포함 파싱. mail 채널에서 Upstage 단어 좌표 + LLM _word_indices → _bbox 부여.
    """
    # 옵션 1: 무조건 upload_channel로만 동작
    if not upload_channel or upload_channel not in ("finet", "mail"):
        raise HTTPException(
            status_code=400,
            detail="upload_channel (finet|mail) is required. form_type 파라미터만 보내는 방식은 더 이상 지원하지 않습니다.",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail=f"Invalid month: {month}. Must be 1-12")

    session_id = SessionManager.generate_session_id()
    results = []
    for uploaded_file in files:
        try:
            pdf_name = Path(uploaded_file.filename).stem
            file_bytes = await uploaded_file.read()
            if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "error",
                    "error": f"File size exceeds {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
                })
                continue
            pdf_filename = f"{pdf_name}.pdf"
            doc_info = db.check_document_exists(pdf_filename)
            if doc_info["exists"]:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "exists",
                    "pages": doc_info.get("total_pages", 0)
                })
            else:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "pending",
                    "pdf_name": pdf_name
                })
                if background_tasks:
                    background_tasks.add_task(
                        process_pdf_background,
                        file_bytes=file_bytes,
                        pdf_name=pdf_name,
                        upload_channel=upload_channel,
                        form_type=None,
                        session_id=session_id,
                        user_id=current_user_id,
                        data_year=year,
                        data_month=month,
                        include_bbox=True,
                    )
        except Exception as e:
            results.append({
                "filename": uploaded_file.filename,
                "status": "error",
                "error": str(e)
            })
    return {
        "message": "Files uploaded (with bbox)",
        "results": results,
        "session_id": session_id
    }


async def process_pdf_background(
    file_bytes: bytes,
    pdf_name: str,
    upload_channel: str,
    form_type: Optional[str],
    session_id: str,
    user_id: int,
    data_year: Optional[int] = None,
    data_month: Optional[int] = None,
    include_bbox: bool = False,
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
                upload_channel=upload_channel,
                user_id=user_id,
                data_year=data_year,
                data_month=data_month,
                include_bbox=include_bbox,
            )
        )
        
        if success:
            pdf_filename = f"{pdf_name}.pdf"
            try:
                from database.registry import get_db
                from datetime import datetime
                db = get_db()
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    # form_type은 processor에서 RAG 참조 기준으로 저장됨. 여기서 덮어쓰지 않음.
                    if data_year and data_month:
                        created_at = datetime(data_year, data_month, 1)
                        cursor.execute("""
                            UPDATE documents_current 
                            SET upload_channel = %s, created_at = %s, data_year = %s, data_month = %s
                            WHERE pdf_filename = %s
                        """, (upload_channel, created_at, data_year, data_month, pdf_filename))
                    else:
                        cursor.execute("""
                            UPDATE documents_current 
                            SET upload_channel = %s 
                            WHERE pdf_filename = %s
                        """, (upload_channel, pdf_filename))
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
        try:
            await manager.send_progress(session_id, {
                "type": "error",
                "file_name": f"{pdf_name}.pdf",
                "error": str(e),
                "message": f"Processing failed: {str(e)}"
            })
        except Exception:
            pass
    finally:
        # 처리 완료 후 temp 폴더의 PDF 파일 및 세션 디렉토리 정리
        # 이미지로 변환되어 static 폴더에 저장되므로 temp 폴더의 파일은 더 이상 필요 없음
        try:
            if pdf_path and pdf_path.exists():
                pdf_path.unlink()
            
            # 세션 디렉토리 내 모든 파일 정리
            if pdf_path:
                pdfs_dir = pdf_path.parent  # temp/{session_id}/pdfs
                session_dir = pdfs_dir.parent  # temp/{session_id}
                
                # pdfs 디렉토리 내 모든 파일 삭제
                if pdfs_dir.exists():
                    for file in pdfs_dir.iterdir():
                        if file.is_file():
                            file.unlink()
                    # pdfs 디렉토리가 비어있으면 삭제
                    if not any(pdfs_dir.iterdir()):
                        pdfs_dir.rmdir()
                
                # 세션 디렉토리 내 다른 파일들도 정리 (OCR 결과 JSON 등)
                if session_dir.exists():
                    for item in session_dir.iterdir():
                        if item.is_file():
                            item.unlink()
                    # 세션 디렉토리가 비어있으면 삭제
                    if not any(session_dir.iterdir()):
                        session_dir.rmdir()
        except Exception:
            pass


@router.get("/", response_model=DocumentListResponse)
async def get_documents(
    form_type: Optional[str] = None,
    upload_channel: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db=Depends(get_db)
):
    """
    문서 목록 조회 (current/archive 테이블 사용)
    
    Args:
        form_type: 양식지 타입 필터 (하위 호환)
        upload_channel: 업로드 채널 필터 (finet | mail)
        year: 연도 (선택사항)
        month: 월 (선택사항)
        db: 데이터베이스 인스턴스
    """
    total_start = time.perf_counter()
    
    try:
        rows = query_documents_table(db, form_type=form_type, upload_channel=upload_channel, year=year, month=month)
        
        # 배치로 첫 페이지의 page_meta 일괄 조회 (N+1 쿼리 문제 해결)
        pdf_filenames = [row[0] for row in rows]
        page_meta_rows = query_page_meta_batch(db, pdf_filenames, year=year, month=month)
        
        # 데이터 처리 시간 측정
        processing_start = time.perf_counter()
        documents = []
        for row in rows:
            pdf_filename = row[0]
            total_pages = row[1]
            row_form_type = row[2]
            row_upload_channel = row[3] if len(row) > 3 else None
            created_at = row[4] if len(row) > 4 else row[3] if len(row) == 4 else None
            data_year = row[5] if len(row) > 5 else (row[4] if len(row) > 4 else None)
            data_month = row[6] if len(row) > 6 else (row[5] if len(row) > 5 else None)
            is_answer_key_document = bool(row[7]) if len(row) > 7 else False
            
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
                    except Exception:
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
                        except Exception:
                            pass
            
            documents.append(DocumentResponse(
                pdf_filename=pdf_filename,
                total_pages=total_pages,
                form_type=row_form_type,
                upload_channel=row_upload_channel,
                status="completed",
                created_at=created_at_str,
                data_year=data_year,
                data_month=data_month,
                is_answer_key_document=is_answer_key_document
            ))
        
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
                except Exception:
                    created_at_str = None
        
        # 문서의 첫 번째 페이지에서 請求年月 추출
        year_month = get_document_year_month(db, pdf_filename)
        data_year = year_month[0] if year_month else None
        data_month = year_month[1] if year_month else None
        
        is_answer_key = bool(doc.get('is_answer_key_document', False))
        return DocumentResponse(
            pdf_filename=doc['pdf_filename'],
            total_pages=doc['total_pages'],
            form_type=doc.get('form_type'),
            upload_channel=doc.get('upload_channel'),
            status="completed",
            created_at=created_at_str,
            data_year=data_year,
            data_month=data_month,
            is_answer_key_document=is_answer_key
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/answer-key-designate")
async def designate_document_as_answer_key(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서를 정답지 생성 대상으로 지정 (검토 탭에서 제외, 정답지 생성 탭에서만 표시)
    - documents_current 또는 documents_archive의 is_answer_key_document = TRUE
    - 해당 문서의 모든 페이지에 page_data의 is_rag_candidate = TRUE
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documents_current
                SET is_answer_key_document = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (pdf_filename,))
            if cursor.rowcount > 0:
                cursor.execute("""
                    UPDATE page_data_current
                    SET is_rag_candidate = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
            else:
                cursor.execute("""
                    UPDATE documents_archive
                    SET is_answer_key_document = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Document not found in current or archive table")
                cursor.execute("""
                    UPDATE page_data_archive
                    SET is_rag_candidate = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
            conn.commit()
        return {"success": True, "message": "Document designated for answer key creation"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/answer-key-revoke")
async def revoke_document_answer_key(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서의 정답지 생성 대상 지정 해제 (검토 탭에서 다시 표시됨)
    - documents_current 또는 documents_archive의 is_answer_key_document = FALSE
    - 해당 문서의 모든 페이지에 page_data의 is_rag_candidate = FALSE
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documents_current
                SET is_answer_key_document = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (pdf_filename,))
            if cursor.rowcount > 0:
                cursor.execute("""
                    UPDATE page_data_current
                    SET is_rag_candidate = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
            else:
                cursor.execute("""
                    UPDATE documents_archive
                    SET is_answer_key_document = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Document not found in current or archive table")
                cursor.execute("""
                    UPDATE page_data_archive
                    SET is_rag_candidate = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (pdf_filename,))
            conn.commit()
        return {"success": True, "message": "Document revoked from answer key creation"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-answer")
async def generate_answer_with_gemini(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    Gemini Vision zero-shot으로 해당 페이지의 정답지(items) 생성.
    페이지 이미지를 Gemini에 전달하여 구조화된 JSON을 추출합니다.
    """
    try:
        from PIL import Image
        from modules.core.extractors.gemini_extractor import GeminiVisionParser

        image_path = db.get_page_image_path(pdf_filename, page_number)
        if not image_path or not Path(image_path).exists():
            raise HTTPException(status_code=404, detail="Page image not found")

        image = Image.open(image_path).convert("RGB")
        debug_dir = _answer_key_debug_dir(pdf_filename)
        # 정답지 생성용 Gemini 모델은 전역 설정(rag_config.gemini_extractor_model)에 따라 동작
        parser = GeminiVisionParser(model_name=getattr(rag_config, "gemini_extractor_model", "gemini-2.5-flash-lite"))
        result = await asyncio.to_thread(
            parser.parse_image,
            image,
            max_size=1200,
            debug_dir=str(debug_dir),
            page_number=page_number,
        )

        items = result.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            items = []

        # 디버깅: 영문 키 생성 위치 추적 — Gemini가 반환한 첫 item의 키를 로그
        try:
            from modules.utils.config import get_gemini_prompt_path
            _prompt_name = get_gemini_prompt_path().name
            _first_keys = list(items[0].keys()) if items and isinstance(items[0], dict) else []
            print(f"[generate_answer_with_gemini] prompt_file={_prompt_name} first_item_keys={_first_keys}")
        except Exception:
            pass

        page_role = result.get("page_role") or "detail"
        # page_meta: items, page_role 제외한 나머지 키 (document_ref 등)
        page_meta = {
            k: v for k, v in result.items()
            if k not in ("items", "page_role") and v is not None
        }

        return {
            "success": True,
            "page_number": page_number,
            "page_role": page_role,
            "page_meta": page_meta if page_meta else None,
            "items": items,
        }
    except HTTPException:
        raise
    except ValueError as e:
        if "GEMINI_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY가 설정되지 않았습니다.")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-answer-gpt")
async def generate_answer_with_gpt(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db),
    model: str = "gpt-5.2-2025-12-11",
):
    """
    동일한 프롬프트(prompt_v3.txt)로 GPT Vision에 이미지를 넘겨 정답지(items) 생성.
    정답지 생성 탭에서는 Gemini 3 Pro Preview 또는 GPT 5.2만 사용.
    """
    try:
        from PIL import Image
        from openai import OpenAI
        from modules.utils.config import load_gemini_prompt, get_gemini_prompt_path

        image_path = db.get_page_image_path(pdf_filename, page_number)
        if not image_path or not Path(image_path).exists():
            raise HTTPException(status_code=404, detail="Page image not found")

        image = Image.open(image_path).convert("RGB")
        # API 크기 제한 고려해 리사이즈 (1200 기준)
        max_size = 1200
        w, h = image.size
        if w > max_size or h > max_size:
            ratio = min(max_size / w, max_size / h)
            image = image.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

        prompt = load_gemini_prompt()
        api_key = getattr(settings, "openai_api_key", None) or __import__("os").getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")

        client = OpenAI(api_key=api_key)
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }
                ],
                max_completion_tokens=4096,
            )
        )
        raw_text = (response.choices[0].message.content or "").strip()
        if not raw_text:
            raise HTTPException(status_code=502, detail="GPT returned empty content")

        # 디버깅: debug/answer_key/{문서명}/ 에 프롬프트·원문·파싱 결과 저장
        try:
            debug_path = _answer_key_debug_dir(pdf_filename)
            debug_path.mkdir(parents=True, exist_ok=True)
            (debug_path / f"page_{page_number}_prompt.txt").write_text(prompt, encoding="utf-8")
            (debug_path / f"page_{page_number}_response.txt").write_text(raw_text, encoding="utf-8")
        except Exception as e:
            print(f"[generate_answer_with_gpt] debug 저장 실패: {e}")

        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not json_match:
            raise HTTPException(status_code=502, detail="GPT response did not contain JSON")
        result = json.loads(json_match.group())

        try:
            debug_path = _answer_key_debug_dir(pdf_filename)
            (debug_path / f"page_{page_number}_response_parsed.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[generate_answer_with_gpt] debug parsed 저장 실패: {e}")

        items = result.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            items = []

        try:
            _prompt_name = get_gemini_prompt_path().name
            _first_keys = list(items[0].keys()) if items and isinstance(items[0], dict) else []
            print(f"[generate_answer_with_gpt] model={model} prompt_file={_prompt_name} first_item_keys={_first_keys}")
        except Exception:
            pass

        page_role = result.get("page_role") or "detail"
        page_meta = {
            k: v for k, v in result.items()
            if k not in ("items", "page_role") and v is not None
        }
        return {
            "success": True,
            "page_number": page_number,
            "page_role": page_role,
            "page_meta": page_meta if page_meta else None,
            "items": items,
            "provider": "gpt",
            "model": model,
        }
    except HTTPException:
        raise
    except ValueError as e:
        if "OPENAI_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateItemsFromAnswerRequest(BaseModel):
    """Gemini 생성 결과로 items 생성 요청"""
    items: list
    page_role: Optional[str] = "detail"
    page_meta: Optional[dict] = None


class GenerateItemsFromTemplateRequest(BaseModel):
    """첫 행(템플릿)으로 나머지 행 LLM 생성 요청"""
    template_item: dict  # 한 행의 키-값 (키 추가/삭제/편집 가능)


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-items-from-template")
async def generate_items_from_template(
    pdf_filename: str,
    page_number: int,
    body: GenerateItemsFromTemplateRequest,
    db=Depends(get_db)
):
    """
    첫 행(템플릿)만 사용자가 편집한 뒤, LLM으로 같은 키 구조의 나머지 행을 생성하여 페이지 전체 items로 교체.
    """
    import json
    try:
        from PIL import Image
        from modules.core.extractors.gemini_extractor import GeminiVisionParser

        template_item = body.template_item if isinstance(body.template_item, dict) else {}
        if not template_item:
            raise HTTPException(status_code=400, detail="template_item is required")

        image_path = db.get_page_image_path(pdf_filename, page_number)
        if not image_path or not Path(image_path).exists():
            raise HTTPException(status_code=404, detail="Page image not found")

        image = Image.open(image_path).convert("RGB")
        # 템플릿 기반 생성도 동일한 Gemini 모델(rag_config.gemini_extractor_model)을 사용
        parser = GeminiVisionParser(model_name=getattr(rag_config, "gemini_extractor_model", "gemini-2.5-flash-lite"))
        result = await asyncio.to_thread(
            parser.parse_image_with_template, image, template_item, max_size=1200
        )

        items = result.get("items") or []
        if not isinstance(items, list):
            items = []
        page_role = result.get("page_role") or "detail"

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                (pdf_filename,)
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Document not found")

            cursor.execute(
                "DELETE FROM items_current WHERE pdf_filename = %s AND page_number = %s",
                (pdf_filename, page_number)
            )

            cursor.execute("""
                INSERT INTO page_data_current (pdf_filename, page_number, page_role)
                VALUES (%s, %s, %s)
                ON CONFLICT (pdf_filename, page_number)
                DO UPDATE SET page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role)
            """, (pdf_filename, page_number, page_role))

            cursor.execute(
                "SELECT form_type FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                (pdf_filename,)
            )
            row = cursor.fetchone()
            form_type = row[0] if row and row[0] else None
            for item_order, item_dict in enumerate(items, 1):
                if not isinstance(item_dict, dict):
                    continue
                separated = db._separate_item_fields(item_dict, form_type=form_type)
                item_data = separated.get("item_data") or {}
                cursor.execute("""
                    INSERT INTO items_current (
                        pdf_filename, page_number, item_order,
                        first_review_checked, second_review_checked,
                        item_data
                    )
                    VALUES (%s, %s, %s, FALSE, FALSE, %s::jsonb)
                """, (
                    pdf_filename, page_number, item_order,
                    json.dumps(item_data, ensure_ascii=False)
                ))

        return {
            "success": True,
            "page_number": page_number,
            "items_count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except ValueError as e:
        if "GEMINI_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY가 설정되지 않았습니다.")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/create-items-from-answer")
async def create_items_from_answer(
    pdf_filename: str,
    page_number: int,
    body: CreateItemsFromAnswerRequest,
    db=Depends(get_db)
):
    """
    Gemini 생성 결과(items)로 해당 페이지에 items를 새로 생성.
    page_data가 없으면 생성하고, items를 순서대로 INSERT합니다.
    """
    import json
    try:
        items = body.items if isinstance(body.items, list) else []
        page_role = body.page_role or "detail"
        page_meta = body.page_meta if isinstance(body.page_meta, dict) else None
        page_meta_json = json.dumps(page_meta, ensure_ascii=False) if page_meta else None

        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. 문서 존재 확인
            cursor.execute(
                "SELECT 1 FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                (pdf_filename,)
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Document not found")

            # 2. page_data 생성/갱신 (page_role, page_meta 포함)
            if page_meta_json:
                cursor.execute("""
                    INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (pdf_filename, page_number)
                    DO UPDATE SET
                        page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role),
                        page_meta = COALESCE(EXCLUDED.page_meta, page_data_current.page_meta)
                """, (pdf_filename, page_number, page_role, page_meta_json))
            else:
                cursor.execute("""
                    INSERT INTO page_data_current (pdf_filename, page_number, page_role)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (pdf_filename, page_number)
                    DO UPDATE SET page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role)
                """, (pdf_filename, page_number, page_role))

            # 3. 공통 필드 분리 후 items INSERT (표준 키 得意先, 商品名)
            cursor.execute(
                "SELECT form_type FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                (pdf_filename,)
            )
            row = cursor.fetchone()
            form_type = row[0] if row and row[0] else None
            for item_order, item_dict in enumerate(items, 1):
                if not isinstance(item_dict, dict):
                    continue
                separated = db._separate_item_fields(item_dict, form_type=form_type)
                item_data = separated.get("item_data") or {}
                customer = separated.get("customer")

                cursor.execute("""
                    INSERT INTO items_current (
                        pdf_filename, page_number, item_order,
                        customer,
                        first_review_checked, second_review_checked,
                        item_data
                    )
                    VALUES (%s, %s, %s, %s, FALSE, FALSE, %s::jsonb)
                """, (
                    pdf_filename, page_number, item_order,
                    customer,
                    json.dumps(item_data, ensure_ascii=False)
                ))

            # 4. document_metadata.item_data_keys 갱신 — 저장 후 refetch 시 RAG 영문 key_order가 아닌 이 문서의 키 순서 사용
            if items and isinstance(items[0], dict):
                item_data_keys = list(items[0].keys())
                if item_data_keys:
                    cursor.execute("""
                        UPDATE documents_current
                        SET document_metadata = COALESCE(document_metadata, '{}'::jsonb) || %s::jsonb
                        WHERE pdf_filename = %s
                    """, (json.dumps({"item_data_keys": item_data_keys}, ensure_ascii=False), pdf_filename))

        return {
            "success": True,
            "created_count": len(items),
            "page_number": page_number,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FormTypeUpdateRequest(BaseModel):
    """양식지 타입 변경 요청"""
    form_type: str


@router.patch("/{pdf_filename}/form-type")
async def update_document_form_type(
    pdf_filename: str,
    body: FormTypeUpdateRequest,
    db=Depends(get_db)
):
    """
    문서의 양식지 타입(form_type) 변경
    검토 탭에서 참조 양식지를 수동으로 수정할 때 사용
    """
    form_type = body.form_type.strip()
    if not form_type or len(form_type) > 10:
        raise HTTPException(status_code=400, detail="form_type must be 1-10 characters (e.g. 01, 02, 07)")

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documents_current 
                SET form_type = %s, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (form_type, pdf_filename))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Document not found")
            conn.commit()
        return {"form_type": form_type, "message": "Form type updated"}
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


class PageMetaUpdateRequest(BaseModel):
    """page_meta 업데이트 요청"""
    page_meta: dict


@router.patch("/{pdf_filename}/pages/{page_number}/meta")
async def update_page_meta(
    pdf_filename: str,
    page_number: int,
    body: PageMetaUpdateRequest,
    db=Depends(get_db)
):
    """
    특정 페이지의 page_meta 업데이트 (정답지 생성 탭에서 편집 저장용)
    """
    try:
        page_meta_json = json.dumps(body.page_meta, ensure_ascii=False) if body.page_meta else "{}"
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE page_data_current
                SET page_meta = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s AND page_number = %s
            """, (page_meta_json, pdf_filename, page_number))
            if cursor.rowcount > 0:
                return {"success": True, "message": "page_meta updated"}
            cursor.execute("""
                UPDATE page_data_archive
                SET page_meta = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s AND page_number = %s
            """, (page_meta_json, pdf_filename, page_number))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Page not found")
        return {"success": True, "message": "page_meta updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
