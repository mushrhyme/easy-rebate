"""
OCR 텍스트 정규화 유틸리티

반각/전각 문자 정규화를 위한 함수 제공
Upstage OCR 등에서 「１　１　４　ｇ」처럼 무게/용량이 공백으로 쪼개지는 패턴을
「１１４ｇ」처럼 붙이는 후처리 포함.
"""
import re
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


def merge_spaced_weight_gram(text: str) -> str:
    """
    OCR에서 무게/용량이 공백으로 쪼개진 패턴을 한 토큰으로 붙인다.
    例: 辛ラーメンバケツカップ　１　１　４　ｇ → 辛ラーメンバケツカップ　１１４ｇ
    全角数字(０-９)와 全角ｇ 사이의 공백(全角・半角)을 제거하여 하나의 숫자+単位로 만든다.
    """
    # １　１　４　ｇ のような「全角数字＋空白」の連続の末尾が ｇ の部分だけを対象
    pattern = r'((?:[０-９][　\s]*)+[　\s]*ｇ)'
    def repl(m: re.Match) -> str:
        s = m.group(1)
        return ''.join(c for c in s if c in '０１２３４５６７８９ｇ')
    return re.sub(pattern, repl, text)


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

    # 3. Upstage 등 OCR에서 무게가 공백으로 쪼개진 패턴(１　１　４　ｇ → １１４ｇ) 보정
    final_text = merge_spaced_weight_gram(final_text)

    return final_text
