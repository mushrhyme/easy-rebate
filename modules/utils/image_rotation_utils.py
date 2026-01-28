"""
이미지 회전 감지 및 보정 유틸리티 모듈

PyTesseract의 OSD (Orientation and Script Detection) 기능을 사용하여
이미지의 회전 각도를 감지하고 자동으로 보정합니다.
"""

import os
import shutil
from typing import Optional, Tuple
from PIL import Image

try:
    import pytesseract
    
    # Tesseract 경로 자동 설정
    def _setup_tesseract_path():
        """Tesseract 실행 파일 경로를 자동으로 설정합니다."""
        tesseract_cmd = shutil.which('tesseract')
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            return tesseract_cmd
        
        # Conda 환경의 기본 경로 시도
        conda_tesseract = "/opt/anaconda3/envs/rebate/bin/tesseract"
        if os.path.exists(conda_tesseract):
            pytesseract.pytesseract.tesseract_cmd = conda_tesseract
            return conda_tesseract
        
        # 다른 일반적인 경로들 시도
        common_paths = [
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
            "/opt/homebrew/bin/tesseract",
        ]
        for path in common_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                return path
        
        return None
    
    _setup_tesseract_path()
    TESSERACT_AVAILABLE = True
    
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None


def detect_rotation(image: Image.Image) -> Optional[int]:
    """
    이미지의 회전 각도를 감지합니다.
    
    Args:
        image: PIL Image 객체
        
    Returns:
        회전 각도 (0, 90, 180, 270) 또는 None (감지 실패 시)
        
    Example:
        >>> from PIL import Image
        >>> image = Image.open("document.png")
        >>> angle = detect_rotation(image)
        >>> print(f"회전 각도: {angle}도")
    """
    if not TESSERACT_AVAILABLE:
        raise ImportError(
            "pytesseract가 설치되지 않았습니다. "
            "설치: pip install pytesseract\n"
            "또한 Tesseract OCR 엔진도 설치해야 합니다:\n"
            "  - Conda: conda install -c conda-forge tesseract\n"
            "  - macOS: brew install tesseract\n"
            "  - Ubuntu: sudo apt-get install tesseract-ocr"
        )
    
    try:
        # OSD (Orientation and Script Detection) 실행
        osd = pytesseract.image_to_osd(image)
        
        # 회전 각도 추출
        rotation_angle = None
        for line in osd.split('\n'):
            if 'Rotate:' in line:
                rotation_angle = int(line.split(':')[1].strip())
                break
        
        return rotation_angle
        
    except Exception as e:
        # OSD 감지 실패 (텍스트가 없거나 감지 불가능한 경우)
        return None


def correct_rotation(image: Image.Image, angle: int) -> Image.Image:
    """
    이미지를 주어진 각도만큼 회전 보정합니다.
    
    Args:
        image: PIL Image 객체
        angle: 회전 각도 (0, 90, 180, 270)
        
    Returns:
        보정된 PIL Image 객체
        
    Example:
        >>> corrected = correct_rotation(image, 90)
    """
    if angle == 0:
        return image
    
    # 시계 반대 방향으로 회전 (음수 각도)
    corrected_image = image.rotate(-angle, expand=True)
    return corrected_image


def detect_and_correct_rotation(
    image: Image.Image,
    return_angle: bool = False
) -> Image.Image | Tuple[Image.Image, Optional[int]]:
    """
    이미지의 회전 각도를 감지하고 자동으로 보정합니다.
    
    Args:
        image: PIL Image 객체
        return_angle: True이면 (보정된_이미지, 회전_각도) 튜플 반환,
                     False이면 보정된_이미지만 반환 (기본값: False)
        
    Returns:
        return_angle=False: 보정된 PIL Image 객체
        return_angle=True: (보정된 PIL Image 객체, 회전 각도) 튜플
        
    Example:
        >>> # 회전 보정만 필요할 때
        >>> corrected = detect_and_correct_rotation(image)
        
        >>> # 회전 각도도 확인하고 싶을 때
        >>> corrected, angle = detect_and_correct_rotation(image, return_angle=True)
        >>> if angle:
        ...     print(f"{angle}도 회전을 보정했습니다.")
    """
    rotation_angle = detect_rotation(image)
    
    if rotation_angle is None:
        # 회전 감지 실패 시 원본 이미지 반환
        if return_angle:
            return image, None
        return image
    
    if rotation_angle == 0:
        # 회전이 없으면 원본 이미지 반환
        if return_angle:
            return image, 0
        return image
    
    # 회전 보정
    corrected_image = correct_rotation(image, rotation_angle)
    
    if return_angle:
        return corrected_image, rotation_angle
    return corrected_image


def is_rotation_detection_available() -> bool:
    """
    회전 감지 기능 사용 가능 여부를 확인합니다.
    
    Returns:
        True: pytesseract와 tesseract가 모두 사용 가능
        False: 사용 불가능
    """
    return TESSERACT_AVAILABLE
