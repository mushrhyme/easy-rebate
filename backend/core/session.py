"""
세션 관리 모듈 (FastAPI용)
Streamlit의 SessionManager를 대체
"""
import os
import uuid
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import UploadFile
from backend.core.config import settings


class SessionManager:
    """FastAPI용 세션 관리 클래스"""
    
    BASE_TMP_DIR = settings.TEMP_DIR
    
    @staticmethod
    def get_project_root() -> Path:
        """프로젝트 루트 디렉토리 경로 반환"""
        from modules.utils.config import get_project_root
        return get_project_root()
    
    @staticmethod
    def generate_session_id() -> str:
        """
        새로운 세션 ID 생성
        
        Returns:
            세션 ID 문자열
        """
        return str(uuid.uuid4())
    
    @staticmethod
    def get_session_dir(session_id: str) -> Path:
        """
        세션별 작업 디렉토리 경로 반환
        
        Args:
            session_id: 세션 ID
            
        Returns:
            세션 디렉토리 Path
        """
        session_dir = Path(SessionManager.BASE_TMP_DIR) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
    
    @staticmethod
    def get_pdfs_dir(session_id: str) -> Path:
        """
        세션별 PDF 저장 디렉토리
        
        Args:
            session_id: 세션 ID
            
        Returns:
            PDF 디렉토리 Path
        """
        session_dir = SessionManager.get_session_dir(session_id)
        pdfs_dir = session_dir / "pdfs"
        pdfs_dir.mkdir(parents=True, exist_ok=True)
        return pdfs_dir
    
    @staticmethod
    def get_images_dir() -> Path:
        """
        이미지 저장 디렉토리 (프로젝트 루트)
        
        Returns:
            img/ 경로
        """
        project_root = SessionManager.get_project_root()
        images_dir = project_root / "img"
        images_dir.mkdir(parents=True, exist_ok=True)
        return images_dir
    
    @staticmethod
    async def save_pdf_file(uploaded_file: UploadFile, pdf_name: str, session_id: str) -> Path:
        """
        업로드된 PDF 파일을 저장
        
        Args:
            uploaded_file: FastAPI UploadFile 객체
            pdf_name: PDF 파일명 (확장자 제외)
            session_id: 세션 ID
            
        Returns:
            저장된 PDF 파일 경로
        """
        pdfs_dir = SessionManager.get_pdfs_dir(session_id)
        pdf_filename = f"{pdf_name}.pdf"
        pdf_path = pdfs_dir / pdf_filename
        
        # 파일 저장
        with open(pdf_path, "wb") as f:
            content = await uploaded_file.read()
            f.write(content)
        
        return pdf_path
    
    @staticmethod
    def save_pdf_file_from_bytes(file_bytes: bytes, pdf_name: str, session_id: str) -> Path:
        """
        바이트 데이터로부터 PDF 파일 저장
        
        Args:
            file_bytes: PDF 파일 바이트 데이터
            pdf_name: PDF 파일명 (확장자 제외)
            session_id: 세션 ID
            
        Returns:
            저장된 PDF 파일 경로
        """
        pdfs_dir = SessionManager.get_pdfs_dir(session_id)
        pdf_filename = f"{pdf_name}.pdf"
        pdf_path = pdfs_dir / pdf_filename
        
        # 파일 저장
        with open(pdf_path, "wb") as f:
            f.write(file_bytes)
        
        return pdf_path
