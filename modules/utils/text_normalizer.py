"""
OCR 텍스트 정규화 유틸리티

반각/전각 문자 정규화를 위한 함수 제공
"""
import unicodedata


def to_fullwidth(text: str) -> str:
    """
    반각 문자를 전각 문자로 변환
    
    Args:
        text: 변환할 텍스트
        
    Returns:
        전각 문자로 변환된 텍스트
    """
    result = []
    for char in text:
        code = ord(char)
        # ASCII 영역 (0x0020-0x007E)를 전각으로 변환
        if 0x0020 <= code <= 0x007E:
            # 공백은 전각 공백으로
            if code == 0x0020:
                result.append('\u3000')  # 전각 공백
            else:
                # ASCII 문자를 전각으로 변환 (0xFF01-0xFF5E)
                result.append(chr(code + 0xFEE0))
        else:
            # 그 외 문자는 그대로 유지
            result.append(char)
    return ''.join(result)


def normalize_ocr_text(ocr_text: str, use_fullwidth: bool = True) -> str:
    """
    OCR 텍스트를 정규화
    
    1. 우선 반각으로 정규화 (NFKC - 노이즈 제거)
    2. 시스템 요구가 전각이면 다시 전각 변환
    
    Args:
        ocr_text: 원본 OCR 텍스트
        use_fullwidth: True면 전각 변환, False면 반각 유지
        
    Returns:
        정규화된 텍스트
    """
    # 1. 우선 반각으로 정규화 (노이즈 제거)
    normalized = unicodedata.normalize("NFKC", ocr_text)
    
    # 2. 시스템 요구가 전각이면 다시 전각 변환
    if use_fullwidth:
        final_text = to_fullwidth(normalized)
    else:
        final_text = normalized
    
    return final_text
