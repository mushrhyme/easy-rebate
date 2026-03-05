"""
세션 관리 유틸리티 모듈
다중 사용자 환경에서 session_id 기반으로 파일을 분리하여 저장
"""

import os
import json
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime


class SessionManager:
    """세션별 파일 관리 클래스"""
    
    BASE_TMP_DIR = "/tmp"  
    
    @staticmethod
    def get_project_root() -> str:
        """프로젝트 루트 디렉토리 경로 반환"""
        # app.py가 있는 디렉토리를 프로젝트 루트로 사용
        if hasattr(sys, '_getframe'):
            frame = sys._getframe(1)
            while frame:
                filename = frame.f_globals.get('__file__', '')
                if filename and 'app.py' in filename:
                    return str(Path(filename).parent)
                frame = frame.f_back
        # fallback: 현재 작업 디렉토리
        return os.getcwd()
    
    @staticmethod
    def get_session_id() -> str:
        """
        현재 프로세스/요청 기준 세션 ID 반환
        
        Returns:
            세션 ID 문자열
        """
        # 환경 변수에 SESSION_ID가 지정된 경우 우선 사용
        env_session_id = os.environ.get("SESSION_ID")
        if env_session_id:
            return env_session_id

        # 프로세스 단위 캐시 사용 (Streamlit 제거)
        if not hasattr(SessionManager, "_SESSION_ID"):
            SessionManager._SESSION_ID = str(uuid.uuid4())
        return SessionManager._SESSION_ID
    
    @staticmethod
    def get_session_dir() -> str:
        """
        현재 세션의 작업 디렉토리 경로 반환
        
        Returns:
            /tmp/{session_id}/ 경로
        """
        session_id = SessionManager.get_session_id()
        session_dir = os.path.join(SessionManager.BASE_TMP_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)
        return session_dir
    
    @staticmethod
    def get_pdfs_dir() -> str:
        """
        세션별 PDF 저장 디렉토리
        
        Returns:
            /tmp/{session_id}/pdfs/ 경로
        """
        session_dir = SessionManager.get_session_dir()
        pdfs_dir = os.path.join(session_dir, "pdfs")
        os.makedirs(pdfs_dir, exist_ok=True)
        return pdfs_dir
    
    @staticmethod
    def get_images_dir() -> str:
        """
        이미지 저장 디렉토리 (프로젝트 루트)
        
        Returns:
            img/ 경로
        """
        project_root = SessionManager.get_project_root()
        images_dir = os.path.join(project_root, "img")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir
    
    @staticmethod
    def get_results_dir() -> str:
        """
        OCR 결과 저장 디렉토리 (프로젝트 루트)
        
        Returns:
            result/ 경로
        """
        project_root = SessionManager.get_project_root()
        results_dir = os.path.join(project_root, "result")
        os.makedirs(results_dir, exist_ok=True)
        return results_dir
    
    @staticmethod
    def save_pdf_file(uploaded_file, pdf_name: str) -> str:
        """
        업로드된 PDF 파일을 세션 디렉토리에 저장
        
        Args:
            uploaded_file: Streamlit UploadedFile 객체
            pdf_name: PDF 파일명 (확장자 제외)
            
        Returns:
            저장된 PDF 파일 경로
        """
        pdfs_dir = SessionManager.get_pdfs_dir()
        pdf_path = os.path.join(pdfs_dir, f"{pdf_name}.pdf")
        
        with open(pdf_path, 'wb') as f:
            f.write(uploaded_file.getvalue())
        
        return pdf_path
    
    @staticmethod
    def save_page_image(image, pdf_name: str, page_num: int) -> str:
        """
        페이지 이미지를 img 폴더에 저장
        
        Args:
            image: PIL Image 객체
            pdf_name: PDF 파일명 (확장자 제외)
            page_num: 페이지 번호 (1부터 시작)
            
        Returns:
            저장된 이미지 파일 경로
        """
        images_dir = SessionManager.get_images_dir()
        pdf_images_dir = os.path.join(images_dir, pdf_name)
        os.makedirs(pdf_images_dir, exist_ok=True)
        
        image_path = os.path.join(pdf_images_dir, f"page_{page_num}.jpg")  # JPEG 형식
        # RGB 모드로 변환 (JPEG는 RGB만 지원)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(image_path, 'JPEG', quality=95)
        
        return image_path
    
    @staticmethod
    def get_status_dir() -> str:
        """
        분석 상태 저장 디렉토리 (프로젝트 루트)
        
        Returns:
            status/ 경로
        """
        project_root = SessionManager.get_project_root()
        status_dir = os.path.join(project_root, "status")
        os.makedirs(status_dir, exist_ok=True)
        return status_dir
    
    @staticmethod
    def save_analysis_status(pdf_name: str, status: str, pages: int = 0, error: Optional[str] = None) -> bool:
        """
        분석 상태 저장 (파일 시스템 기반)
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            status: 상태 ("processing", "completed", "error", "pending")
            pages: 페이지 수 (기본값: 0)
            error: 에러 메시지 (있는 경우)
            
        Returns:
            저장 성공 여부 (항상 True)
        """
        # 파일 시스템에 상태 JSON 저장
        status_dir = SessionManager.get_status_dir()
        status_path = os.path.join(status_dir, f"{pdf_name}.json")

        data = {
            "status": status,
            "pages": pages,
            "error": error,
            "pdf_name": pdf_name,
        }

        try:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            # 상태 저장 실패해도 애플리케이션 흐름은 막지 않음
            pass

        return True
    
    @staticmethod
    def load_analysis_status(pdf_name: str) -> Optional[Dict[str, Any]]:
        """
        저장된 분석 상태 로드 (파일 시스템 + DB 폴백)
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            
        Returns:
            분석 상태 딕셔너리 또는 None
        """
        # 1. 파일 시스템에서 상태 JSON 조회
        status_dir = SessionManager.get_status_dir()
        status_path = os.path.join(status_dir, f"{pdf_name}.json")

        if os.path.exists(status_path):
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 필드 기본값 보정
                return {
                    "status": data.get("status", "pending"),
                    "pages": data.get("pages", 0),
                    "error": data.get("error"),
                    "pdf_name": data.get("pdf_name", pdf_name),
                }
            except Exception:
                # 손상된 JSON 등은 무시하고 DB 폴백으로 진행
                pass
        
        # DB에서 페이지 수 확인
        try:
            from database.registry import get_db
            
            db_manager = get_db()
            pdf_filename = f"{pdf_name}.pdf"
            
            page_results = db_manager.get_page_results(
                pdf_filename=pdf_filename
            )
            pages = len(page_results) if page_results else 0
            if pages > 0:
                return {
                    "status": "completed",
                    "pages": pages,
                    "error": None,
                    "pdf_name": pdf_name
                }
        except Exception:
            pass
        
        return None
    
    @staticmethod
    def cleanup_session():
        """
        현재 세션의 임시 파일 정리 (선택적)
        """
        session_dir = SessionManager.get_session_dir()
        if os.path.exists(session_dir):
            import shutil
            try:
                shutil.rmtree(session_dir)
            except Exception:
                pass  # 정리 실패해도 무시

