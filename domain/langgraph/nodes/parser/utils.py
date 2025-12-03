from typing import List
import re


def extract_comments(content: str) -> List[str]:
    """간단한 주석 추출 (최대 10개)"""
    comments: List[str] = []
    # Python/Shell 스타일 주석 (#)
    comments.extend([c.strip() for c in re.findall(r'#\s*(.+)', content) if c.strip()])
    # C/JS 한 줄 주석
    comments.extend([c.strip() for c in re.findall(r'//\s*(.+)', content) if c.strip()])
    # C/JS 블록 주석
    for block in re.findall(r'/\*\s*(.+?)\s*\*/', content, re.DOTALL):
        clean = re.sub(r'\s+', ' ', block).strip()
        if clean:
            comments.append(clean)
    return comments[:10]
