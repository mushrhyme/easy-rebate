"""
검색 API
"""
from typing import List, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, Query

from database.registry import get_db

router = APIRouter()


@router.get("/customer")
async def search_by_customer(
    customer_name: str = Query(..., description="거래처명"),
    exact_match: bool = Query(False, description="완전 일치 여부"),
    form_type: Optional[str] = Query(None, description="양식지 타입 필터"),
    db=Depends(get_db)
):
    """
    거래처명으로 검색
    
    Args:
        customer_name: 거래처명
        exact_match: 완전 일치 여부
        form_type: 양식지 타입 필터 (선택사항)
        db: 데이터베이스 인스턴스
    """
    try:
        results = db.search_items_by_customer(
            customer_name=customer_name,
            exact_match=exact_match,
            form_type=form_type
        )
        
        # 파일명과 페이지별로 그룹화
        grouped_results = {}
        for item in results:
            pdf_filename = item.get('pdf_filename')
            page_number = item.get('page_number')
            key = (pdf_filename, page_number)
            
            if key not in grouped_results:
                grouped_results[key] = {
                    'pdf_filename': pdf_filename,
                    'page_number': page_number,
                    'items': [],
                    'form_type': item.get('form_type')
                }
            grouped_results[key]['items'].append(item)
        
        return {
            "query": customer_name,
            "total_items": len(results),
            "total_pages": len(grouped_results),
            "pages": list(grouped_results.values())
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages/{page_number}/image")
async def get_page_image_url(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    페이지 이미지 URL 조회 (page_role 정보 포함)

    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        # 이미지 파일 경로 조회
        image_path = db.get_page_image_path(pdf_filename, page_number)

        # page_role 정보 조회
        # documents.get_page_meta 와 동일하게 db.get_page_result 를 사용하여
        # current / archive 등 테이블 구조 변경에 상관없이 일관된 방식으로 page_role 을 가져온다.
        page_role = None
        try:
            page_result = db.get_page_result(pdf_filename, page_number)
            if page_result:
                page_role = page_result.get("page_role")
        except Exception:
            # page_role 조회 실패 시 None 유지 (배지 비표시)
            pass

        if not image_path:
            raise HTTPException(status_code=404, detail="Image not found")

        # 파일 시스템 경로를 URL 경로로 변환
        # "static/images/..." -> "/static/images/..."
        if image_path.startswith("static/"):
            # 경로의 각 세그먼트를 개별적으로 인코딩 (슬래시는 유지)
            path_parts = image_path.split('/')
            encoded_parts = [quote(part, safe='') for part in path_parts]
            image_url = '/' + '/'.join(encoded_parts)
        else:
            # 이미 URL 경로인 경우 각 세그먼트를 인코딩
            if image_path.startswith('/'):
                path_parts = image_path[1:].split('/')
                encoded_parts = [quote(part, safe='') for part in path_parts]
                image_url = '/' + '/'.join(encoded_parts)
            else:
                path_parts = image_path.split('/')
                encoded_parts = [quote(part, safe='') for part in path_parts]
                image_url = '/'.join(encoded_parts)

        print(f"🖼️ 이미지 URL 생성: {image_path} -> {image_url}")

        response = {
            "image_url": image_url,
            "format": "jpeg"
        }

        # page_role이 있으면 응답에 포함
        if page_role:
            response["page_role"] = page_role

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
