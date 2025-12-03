"""Prompt helper functions for Full Repository Document generation.

Goals:
1. 강한 단일 SYSTEM 역할: 사실 기반, 구조 고정, 환각/추측/중복 차단.
2. 섹션별 Task Prompt: 템플릿을 엄격히 강제 (제목/순서/포맷 불변).
3. 입력 데이터(JSON) Compact: 키 축약, 길이 제한, 최대 파일 수 제한.
4. 문서 규칙: Mermaid 다이어그램 규칙, 리스트 길이 제한, 중복/불필요 표현 차단.

Multiple versions (v1~v4) allow A/B testing of strictness & verbosity.
Use get_prompt_set(version) to obtain (system_prompt, builders).
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Callable, Tuple

MAX_FILES = 40  # max file entries in prompt
PROMPT_VERSIONS = ["v1", "v2", "v3", "v4"]
DEFAULT_VERSION = "v4"

# ============================================================
# Compact data extraction
# ============================================================
def _compact_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in sorted(files, key=lambda x: x.get("file_path", ""))[:MAX_FILES]:
        s = f.get("summary", {}) or {}
        out.append({
            "p": f.get("file_path"),            # path
            "l": f.get("language"),            # language
            "pu": (s.get("purpose") or "")[:90],
            "fn": s.get("functions_count"),
            "cl": s.get("classes_count"),
            "r": s.get("role"),
        })
    return out

# ============================================================
# System Role (shared core) – very strong guardrails
# ============================================================
BASE_SYSTEM_ROLE = (
    "역할: 대규모 코드베이스 기술 문서/아키텍처 전문 작성자\n"
    "언어: 한국어 Markdown (이모지 사용 금지)\n"
    "원칙:\n"
    "- 제공된 JSON 데이터(p,l,pu,fn,cl,r)를 적극 활용하여 합리적 추론 허용\n"
    "- 파일 경로, 언어, 목적(pu), 함수/클래스 수에서 프로젝트 특성 도출\n"
    "- 일반적인 기술 스택 패턴과 아키텍처 관례 적용\n"
    "- 의존성은 파일 경로와 역할(r)에서 논리적 연결 추론\n"
    "- 불분명할 때만 '구체적 정보 부족'으로 표현 ('알 수 없음' 남발 금지)\n"
    "- 구조/제목/순서 절대 변경 금지\n"
    "- 마케팅 표현 지양, 기술적 정확성 우선\n"
)

# Version modifiers (added to BASE_SYSTEM_ROLE)
SYSTEM_VARIANTS = {
    "v1": "목표: 기본 구조 유지, 적당한 설명 허용.",
    "v2": "목표: 엄격한 간결성 (각 문단 최대 3문장, 리스트 항목 최대 6개).", 
    "v3": "목표: 초압축 (각 문장 40자 이하 권장, 리스트 항목 최대 4개).",
    "v4": "목표: 간결하고 구조화된 출력. JSON 메타데이터나 부가 설명 없이 순수 Markdown만 생성.",
}

def build_system_prompt(version: str) -> str:
    if version not in SYSTEM_VARIANTS:
        version = DEFAULT_VERSION
    return (
        f"[SYSTEM version={version}]\n" + BASE_SYSTEM_ROLE + SYSTEM_VARIANTS[version] + "\n" +
        "전역 문서 규칙:\n"
        "- Mermaid 다이어그램: 그래프 1개, graph TD 또는 LR, 노드 <= 12, 엣지 <= 20, 자기 루프/파생 추측 금지\n"
        "- 리스트: 불릿 '- ' 사용, 항목 수 제한 준수\n"
        "- 개선/추천은 구체적 실행 동사로 시작 (예: '도입', '분리', '추가')\n"
        "- 출력 끝에 불필요한 부가 설명 금지\n"
    )

# ============================================================
# Section Task Prompts – enforce template strictly
# ============================================================
def _overview_task(repo_name: str, data_json: str, version: str) -> str:
    return (
        f"[OVERVIEW] 프로젝트: {repo_name}\n"
        "템플릿 고정:\n"
        "# 프로젝트 개요\n"
        "## 1. 목적\n"
        "## 2. 주요 기능\n"
        "## 3. 기술 스택\n"
        "## 4. 아키텍처 개요\n"
        "## 5. 강점/특징\n"
        "요구:\n"
        "- 파일 경로 패턴에서 프로젝트 성격 추론 (예: /api/, /model/, /service/ 등)\n"
        "- 언어(l)와 함수/클래스 수(fn,cl)에서 복잡도와 규모 판단\n"
        "- 목적(pu) 정보를 종합하여 주요 기능 도출\n"
        "- FastAPI, Django, Spring 등 프레임워크는 파일명/경로에서 식별\n"
        "- 데이터베이스, 캐시, 메시징 등은 일반적 패턴으로 추론\n"
        "- '기술 스택'은 계층별 구성 (Frontend/Backend/Database)\n"
        "- '강점/특징'은 아키텍처 특성과 기술 선택의 장점 위주\n"
        f"데이터:{data_json}\n"
    )

def _architecture_task(data_json: str, version: str) -> str:
    return (
        "[ARCHITECTURE]\n"
        "템플릿 고정:\n"
        "# 시스템 아키텍처\n"
        "## 1. 계층 구조\n"
        "## 2. 주요 컴포넌트\n"
        "## 3. 데이터/제어 흐름\n"
        "## 4. Mermaid 다이어그램\n"
        "## 5. 설계 고려사항\n"
        "분석 지침:\n"
        "- 파일 경로 패턴으로 계층 식별: /api/, /service/, /model/, /config/, /utils/ 등\n"
        "- 역할(r) 정보와 목적(pu)으로 컴포넌트 간 관계 추론\n"
        "- 함수/클래스 수로 복잡도 판단하여 핵심 모듈 우선순위 결정\n"
        "- Mermaid 다이어그램 요구사항:\n"
        "  * 실제 파일/폴더 구조 기반으로 노드 생성\n"
        "  * 일반적인 의존성 방향: API → Service → Model → Database\n"
        "  * 설정/유틸리티는 다른 레이어에서 참조되는 구조\n"
        "  * 노드명은 실제 파일명 또는 폴더명 활용\n"
        "- 웹 프레임워크, ORM, 데이터베이스 연결 등 표준 패턴 적용\n"
        f"데이터:{data_json}\n"
    )

def _modules_task(data_json: str, version: str) -> str:
    return (
        "[MODULES]\n"
        "템플릿 고정:\n"
        "# 핵심 모듈\n"
        "(각 모듈 블록 템플릿)\n"
        "### [모듈명]\n"
        "- 목적: \n"
        "- 핵심 기능: (불릿 2~6개, v3는 2~4개)\n"
        "- 의존성: (추론된 내부/외부 의존성)\n"
        "- 기술 특성: (사용 기술과 패턴)\n"
        "- 개선 포인트: (1~3개, 실행 동사 시작)\n"
        "분석 지침:\n"
        "- 폴더/파일 그룹핑으로 모듈 경계 식별\n"
        "- 목적(pu)과 역할(r)로 각 모듈의 책임 정의\n"
        "- 함수/클래스 수로 모듈 복잡도와 중요도 판단\n"
        "- 의존성 추론 방법:\n"
        "  * API 모듈 → Service 모듈 → Data 모듈\n"
        "  * Config/Utils는 다른 모듈들이 의존\n"
        "  * 외부 라이브러리는 파일 확장자와 일반 패턴으로 추론\n"
        "- 언어별 특성 반영 (Python: Django/FastAPI, Java: Spring, JS: Express 등)\n"
        "- 개선 포인트는 아키텍처, 성능, 유지보수성 관점에서 제안\n"
        f"데이터:{data_json}\n"
    )

# ============================================================
# Public API
# ============================================================
def get_prompt_set(version: str = DEFAULT_VERSION) -> Dict[str, Tuple[str, Callable]]:
    """Return dict: section -> (system_prompt, human_builder(files, struct, repo))."""
    if version not in PROMPT_VERSIONS:
        version = DEFAULT_VERSION
    system = build_system_prompt(version)
    def overview_builder(files: List[Dict[str, Any]], structure: Dict[str, Any], repo: str):
        return _overview_task(repo, json.dumps(_compact_files(files), ensure_ascii=False), version)
    def arch_builder(files: List[Dict[str, Any]], structure: Dict[str, Any], repo: str):
        return _architecture_task(json.dumps(_compact_files(files), ensure_ascii=False), version)
    def modules_builder(files: List[Dict[str, Any]], structure: Dict[str, Any], repo: str):
        return _modules_task(json.dumps(_compact_files(files), ensure_ascii=False), version)
    return {
        "overview": (system, overview_builder),
        "architecture": (system, arch_builder),
        "modules": (system, modules_builder),
    }

__all__ = ["get_prompt_set", "PROMPT_VERSIONS", "DEFAULT_VERSION"]


# ==========================
# System Prompts 
# ==========================
BASE_SYSTEM_PROMPT = (
    """당신은 대규모 코드베이스 문서를 작성하는 전문 아키텍트입니다.
출력은 항상 한국어 Markdown을 사용하며, 제공된 데이터만 기반으로 작성합니다.
불확실한 정보는 '알 수 없음'이라 적고, 과도한 추측은 금지합니다.
"""
)

SYSTEM_OVERVIEW = (
    """
아래 파일 요약을 기반으로 '프로젝트 개요' 섹션을 작성하세요.
문서 구조:
## 프로젝트 개요
### 1. 목적
### 2. 주요 기능
### 3. 기술 스택
### 4. 아키텍처 개요
### 5. 강점/특징
"""
)

SYSTEM_ARCHITECTURE = (
    """
아래 파일 요약을 기반으로 시스템 아키텍처 섹션을 작성하고 Mermaid를 포함하세요.
문서 구조:
## 시스템 아키텍처
### 1. 계층/모듈 구조
### 2. 주요 컴포넌트
### 3. 데이터/제어 흐름
### 4. 다이어그램

Mermaid 규칙:
- 코드블럭은 ```mermaid 로 시작
- graph TD 또는 LR 사용
- 노드명은 간결하게
"""
)

SYSTEM_KEY_MODULES = (
    """
아래 파일 요약을 기반으로 핵심 모듈을 정리하세요.
각 모듈은 다음 구조를 따릅니다:
### [모듈명]
- 목적:
- 핵심 기능:
- 의존성:
- 개선 포인트:
"""
)


 # (legacy exports removed – use get_prompt_set)
