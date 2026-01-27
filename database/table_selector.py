"""
테이블 선택 유틸리티

연월에 따라 current 또는 archive 테이블을 선택합니다.
"""

from datetime import datetime
from typing import Optional, Tuple


def get_table_suffix(year: Optional[int] = None, month: Optional[int] = None) -> str:
    """
    연월에 따라 테이블 접미사 반환 (current 또는 archive)
    
    Args:
        year: 연도 (None이면 현재 연도)
        month: 월 (None이면 현재 월)
    
    Returns:
        'current' 또는 'archive'
    """
    now = datetime.now()
    current_year = year or now.year
    current_month = month or now.month
    
    # 현재 연월 계산
    target_year = year if year is not None else current_year
    target_month = month if month is not None else current_month
    
    # 현재 연월과 비교
    if target_year < current_year:
        return 'archive'
    elif target_year == current_year and target_month < current_month:
        return 'archive'
    else:
        return 'current'


def get_table_name(base_name: str, year: Optional[int] = None, month: Optional[int] = None) -> str:
    """
    연월에 따라 테이블 이름 반환
    
    Args:
        base_name: 기본 테이블 이름 (예: 'documents', 'items')
        year: 연도 (None이면 현재 연도)
        month: 월 (None이면 현재 월)
    
    Returns:
        테이블 이름 (예: 'documents_current', 'items_archive')
    """
    suffix = get_table_suffix(year, month)
    return f"{base_name}_{suffix}"


def get_current_year_month() -> Tuple[int, int]:
    """
    현재 연월 반환
    
    Returns:
        (year, month) 튜플
    """
    now = datetime.now()
    return (now.year, now.month)


def is_current_month(year: Optional[int], month: Optional[int]) -> bool:
    """
    주어진 연월이 현재 연월인지 확인
    
    Args:
        year: 연도
        month: 월
    
    Returns:
        현재 연월이면 True, 아니면 False
    """
    if year is None or month is None:
        return False
    
    now = datetime.now()
    return year == now.year and month == now.month
