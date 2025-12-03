from typing import Optional, Dict, List, Any
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ..utils.llm_backoff import invoke_with_retry

from ..document_state import DocumentState

#LLM 또는 Mock을 사용하여 마크다운 문서를 생성/업데이트하는 노드 (섹션 단위 부분 업데이트 포함)


def document_generator_node(
    state: DocumentState,
    llm: Optional[ChatOpenAI] = None,
    use_mock: bool = False
) -> DocumentState:
    """
    문서 생성/업데이트 노드 (통합)
    
    역할:
        - 분석 결과를 기반으로 마크다운 문서 생성/업데이트
        - target_doc_sections 존재 시: 섹션 단위 부분 업데이트
        - target_doc_sections 없을 시: 전체 문서 업데이트 (Changelog 중심)
        - Mock 모드: 템플릿 기반 문서
        - 실제 모드: LLM 기반 고품질 문서
    
    입력:
        - should_update: 업데이트 여부
        - target_doc_sections: 업데이트할 섹션 목록 (선택사항)
        - analysis_result: 변경사항 분석 결과
        - existing_document: 기존 문서 (업데이트 시)
        - code_change: 커밋 정보
        - changed_files: 변경된 파일 목록
        - diff_content: diff 내용 (부분 업데이트 시)
        - llm: ChatOpenAI 인스턴스 (실제 모드)
        - use_mock: Mock 모드 사용 여부
    
    출력:
        - document_content: 생성된 마크다운 문서
        - document_summary: 문서 요약
        - updated_sections: 섹션별 업데이트 정보 (부분 업데이트 시)
        - status: "saving"
    """
    try:
        should_update = state.get("should_update", False)
        analysis_result = state.get("analysis_result", "")
        
        print(f"[DocumentGenerator] should_update: {should_update}")
        print(f"[DocumentGenerator] analysis_result length: {len(analysis_result) if analysis_result else 0}")
        
        # Mock 모드 처리
        if use_mock:
            commit_info = state.get("code_change", {})
            changed_files = state.get("changed_files", []) or []
            commit_sha = commit_info.get("commit_sha", "unknown")[:8] if commit_info else "unknown"
            commit_message = commit_info.get("commit_message", "") if commit_info else ""
            
            mock_content = f"""# {commit_sha} 코드 변경사항

##  변경사항 요약
{analysis_result}

##  커밋 정보
- SHA: {commit_sha}
- 메시지: {commit_message}
- 변경된 파일: {', '.join(changed_files)}

##  상세 내용
Mock 모드로 생성된 문서입니다. 
실제 OpenAI API를 사용하면 더 상세한 분석이 제공됩니다.
"""
            
            state["document_content"] = mock_content
            state["document_summary"] = f"{commit_sha} 커밋의 코드 변경사항 문서"
            state["status"] = "saving"
            return state
        
        # 실제 LLM 사용
        if llm is None:
            raise ValueError("LLM is required for non-mock mode")
        
        if should_update:
            # 섹션 단위 부분 업데이트 체크
            target_sections = state.get("target_doc_sections")
            if target_sections:
                print(f"[DocumentGenerator] Partial update mode: {len(target_sections)} sections")
                return _handle_partial_update(state, llm, use_mock)
            
            # 전체 문서 업데이트
            print("[DocumentGenerator] Full document update mode")
            existing_doc = state.get("existing_document") or {}
            existing_content = existing_doc.get("content", "") if isinstance(existing_doc, dict) else ""
            system_prompt = (
                "당신은 기술 문서 편집 전문가입니다. 전체 재생성 대신 전체 문서 맨 아래에 '## Changelog' 섹션을 만들거나 갱신하고 이번 변경사항을 추가하세요.\n"
                "기존 본문은 수정하지 말고 변경 필요 문맥만 최소화하여 반영." )
            user_prompt = f"""기존 문서 원문:
```markdown
{existing_content}
```

변경 분석 요약:
{analysis_result}

위 변경을 반영한 갱신된 전체 문서를 반환하세요."""
        else:
            # 신규 문서 생성 책임 제거: 상태만 표시하고 작업 건너뜀
            state["status"] = "skip"
            state["error"] = "신규 문서 생성은 full_repository_document_generator에서 처리됩니다."
            return state
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = invoke_with_retry(llm, messages)
        
        content_value = response.content
        if not isinstance(content_value, str):
            # LangChain 메시지 content가 list 형태일 수 있으므로 문자열로 변환
            try:
                content_value = "\n".join([
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content_value
                ])
            except Exception:
                content_value = str(content_value)
        state["document_content"] = content_value
        
        # 요약 생성
        summary_prompt = f"""다음 문서를 3-5줄로 요약하세요:

{response.content}

요약:"""
        
        summary_response = invoke_with_retry(llm, [HumanMessage(content=summary_prompt)])
        summary_value = summary_response.content
        if not isinstance(summary_value, str):
            try:
                summary_value = " ".join([
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in summary_value
                ])
            except Exception:
                summary_value = str(summary_value)
        state["document_summary"] = summary_value
        
        state["status"] = "saving"
        return state
        
    except Exception as e:
        state["error"] = f"Document generator failed: {str(e)}"
        state["status"] = "error"
        return state


# ==================== 섹션 단위 부분 업데이트 헬퍼 ====================

SECTION_KEY_MAP = {
    'overview': ['project overview','overview'],
    'architecture': ['architecture','system design'],
    'modules': ['key modules','modules'],
    'changelog': ['changelog','change log','recent changes'],
}

@dataclass
class ParsedDocument:
    sections: Dict[str, str]
    order: List[str]
    headings: Dict[str, str]

def _normalize_section_key(heading: str) -> str:
    """섹션 제목을 정규화된 키로 변환"""
    lower = heading.lower()
    for key, variants in SECTION_KEY_MAP.items():
        if any(v in lower for v in variants):
            return key
    return re.sub(r'[^a-z0-9]+','_', lower).strip('_')[:40]

def _parse_markdown_sections(content: str) -> ParsedDocument:
    """마크다운을 섹션별로 파싱 (## 기준)"""
    pattern = re.compile(r'^##\s+(.+)$', re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return ParsedDocument(sections={'__full__': content}, order=['__full__'], headings={'__full__': 'Document'})
    
    sections: Dict[str, str] = {}
    order: List[str] = []
    headings: Dict[str, str] = {}
    
    for idx, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        key = _normalize_section_key(heading)
        
        # 중복 키 방지
        unique_key = key
        suffix = 2
        while unique_key in sections:
            unique_key = f"{key}_{suffix}"
            suffix += 1
        
        sections[unique_key] = body
        order.append(unique_key)
        headings[unique_key] = heading
    
    return ParsedDocument(sections=sections, order=order, headings=headings)

def _merge_sections(parsed: ParsedDocument, updated: Dict[str, str]) -> str:
    """업데이트된 섹션만 교체하고 나머지는 원본 유지"""
    lines: List[str] = []
    for key in parsed.order:
        original_heading = parsed.headings.get(key, key.replace('_', ' ').title())
        body = updated.get(key, parsed.sections.get(key, ''))
        lines.append(f"## {original_heading}\n{body.strip()}\n")
    return "\n".join(lines).strip()

def _build_section_prompt(
    section_key: str,
    old_text: str,
    file_summaries: List[dict],
    analysis: str,
    commit_msg: str
) -> tuple[str, str]:
    """
    문서 섹션 업데이트용 system/user 프롬프트 생성.
    - changelog는 특별 처리 (항상 새 항목만 생성)
    - 그 외 섹션은 업데이트/추가/무변경만 출력
    """

    # ------------------------------------------------------------
    # 1) Changelog — 특별 처리
    # ------------------------------------------------------------
    if section_key == "changelog":

        system_prompt = (
            "당신의 역할은 changelog 작성자입니다.\n"
            "이번 커밋에서 새로 발생한 변화만을 요약하여 '신규 changelog 항목'만 생성하세요.\n\n"
            "규칙:\n"
            "- 기존 changelog 내용은 다시 언급하지 않습니다.\n"
            "- 출력 형식: 새로운 bullet 한 개 또는 1~3줄의 짧은 항목\n"
            "- 불필요한 설명, 헤더, Markdown 코드블록 금지\n"
            "- 커밋과 직접 관련된 변경 사항만 포함\n"
        )

        summaries_text = "\n".join([
            f"- {s.get('file')}: {s.get('summary')}"
            for s in file_summaries[:5]  # 상위 5개만
        ])

        user_prompt = (
            f"커밋 메시지:\n{commit_msg}\n\n"
            f"변경된 파일 요약(일부):\n{summaries_text}\n\n"
            f"변경 분석:\n{analysis}\n\n"
            "위 정보를 기반으로 이번 커밋의 새로운 changelog 항목을 생성하세요.\n"
            "출력: 하나의 새로운 bullet만 생성하세요."
        )

        return system_prompt, user_prompt

    # ------------------------------------------------------------
    # 2) 일반 섹션 — 전체 업그레이드 버전
    # ------------------------------------------------------------
    system_prompt = (
        "당신의 역할은 기술 문서 수정 전문가입니다.\n\n"
        "주어진 섹션의 기존 내용을 읽고, 실제 변경이 필요한 부분만 찾아 최소 단위로 업데이트하세요.\n"
        "전체 문서를 다시 쓰는 것이 아니라, '변경된 부분만 정확히 생성'해야 합니다.\n\n"
        "출력 규칙(매우 중요):\n"
        "1. 기존 문장이 수정되어야 하는 경우:\n"
        "   - 수정된 문단만 출력하고\n"
        "   - 맨 앞에 [UPDATE: 기존문구일부] 형태로 표시합니다.\n\n"
        "2. 새로운 내용이 추가되어야 하는 경우:\n"
        "   - 추가 문단만 출력하고\n"
        "   - 맨 앞에 [ADD] 를 붙입니다.\n\n"
        "3. 변화가 전혀 필요하지 않다면:\n"
        "   - 오직 [NO_CHANGE] 만 출력합니다.\n\n"
        "추가 규칙:\n"
        "- 기존 글의 스타일, 톤, 형식을 유지합니다.\n"
        "- 과도한 리라이팅 금지.\n"
        "- 전체 섹션을 다시 작성하지 않습니다.\n"
        "- 변경 근거는 파일 요약 및 분석 내용에서만 찾습니다.\n"
        "- 마크다운 코드블록, 불필요한 텍스트, 해설 금지.\n\n"
        f"현재 섹션: {section_key}"
    )

    summaries_text = "\n".join([
        f"- {s.get('file')} ({s.get('priority')}): {s.get('summary')}"
        for s in file_summaries
    ])

    user_prompt = (
        f"현재 섹션의 기존 내용:\n{old_text}\n\n"
        f"커밋 메시지:\n{commit_msg}\n\n"
        f"변경된 파일 요약:\n{summaries_text}\n\n"
        f"변경 분석:\n{analysis}\n\n"
        "위 정보를 기반으로, 이 섹션에서 '변경이 필요한 부분만' 찾아 아래 규칙에 따라 출력하세요.\n\n"
        "규칙:\n"
        "- 수정된 문단 → [UPDATE: 일부원문] + 수정된 문단\n"
        "- 새로 추가할 문단 → [ADD] + 추가 문단\n"
        "- 변경 필요 없음 → [NO_CHANGE]\n\n"
        "출력: 변경된 문단들만 생성하세요. 설명이나 기타 텍스트는 절대 포함하지 마세요."
    )

    return system_prompt, user_prompt


def _update_section_llm(section_key: str, old_text: str, llm: ChatOpenAI, file_summaries: List[dict], analysis: str, commit_msg: str) -> str:
    """LLM으로 특정 섹션 업데이트 (변경 부분만 생성 후 병합)"""
    system, user = _build_section_prompt(section_key, old_text, file_summaries, analysis, commit_msg)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    resp = invoke_with_retry(llm, messages)
    content = getattr(resp, 'content', '')
    if isinstance(content, list):
        content = '\n'.join(str(c) for c in content)
    
    generated = str(content).strip()
    
    # Changelog는 기존 내용에 추가만
    if section_key == 'changelog':
        return _merge_changelog(old_text, generated)
    
    # 일반 섹션: 변경사항 파싱 및 병합
    return _merge_section_changes(old_text, generated)


def _merge_changelog(old_content: str, new_entry: str) -> str:
    """Changelog 섹션에 새 항목 추가"""
    if not new_entry or '[NO_CHANGE]' in new_entry:
        return old_content
    
    # 기존 내용이 없으면 새 항목만 반환
    if not old_content.strip():
        return new_entry
    
    # 기존 내용 + 새 항목
    return f"{old_content.rstrip()}\n{new_entry}"


def _merge_section_changes(old_content: str, changes: str) -> str:
    """섹션 변경사항을 기존 내용과 병합"""
    if not changes or '[NO_CHANGE]' in changes:
        return old_content
    
    # 변경사항이 없는 경우
    if not old_content.strip():
        cleaned = changes.replace('[ADD]', '').replace('[UPDATE:', '').strip()
        return re.sub(r'\[UPDATE:[^\]]*\]', '', cleaned).strip()
    
    result = old_content
    
    # [UPDATE: ...] 마커가 있는 경우: 내용 교체 (먼저 처리)
    update_pattern = re.compile(r'\[UPDATE:\s*([^\]]+)\]\s*\n*([^\[]*?)(?=\[|$)', re.DOTALL)
    matches = update_pattern.findall(changes)
    
    for original_snippet, new_content in matches:
        snippet = original_snippet.strip()
        new_text = new_content.strip()
        
        if not new_text:
            continue
        
        # 원본에서 해당 텍스트를 포함하는 문단 찾기
        snippet_key = snippet[:30] if len(snippet) > 30 else snippet
        
        # 줄 단위로 찾기
        lines = result.split('\n')
        found = False
        for i, line in enumerate(lines):
            if snippet_key in line or snippet in line:
                # 해당 줄을 새 내용으로 교체
                lines[i] = new_text
                found = True
                break
        
        if found:
            result = '\n'.join(lines)
        else:
            # 문단 단위로 찾기
            paragraphs = result.split('\n\n')
            for i, para in enumerate(paragraphs):
                if snippet_key in para or snippet in para:
                    paragraphs[i] = new_text
                    found = True
                    break
            
            if found:
                result = '\n\n'.join(paragraphs)
            else:
                # 찾지 못하면 끝에 추가
                result = f"{result.rstrip()}\n\n{new_text}"
    
    # [ADD] 마커가 있는 경우: 내용 추가 (나중에 처리)
    add_pattern = re.compile(r'\[ADD\]\s*\n*([^\[]*?)(?=\[|$)', re.DOTALL)
    add_matches = add_pattern.findall(changes)
    
    for add_content in add_matches:
        new_text = add_content.strip()
        if new_text:
            result = f"{result.rstrip()}\n\n{new_text}"
    
    return result.strip()

def _update_section_mock(section_key: str, old_text: str, commit_msg: str) -> str:
    """Mock 모드로 섹션 업데이트 (병합 방식)"""
    if section_key == 'changelog':
        # Changelog는 항상 추가
        new_entry = f"- {commit_msg[:60]}"
        return _merge_changelog(old_text, new_entry)
    
    # 일반 섹션: 간단한 추가 주석
    mock_addition = f"\n\n*Updated: {commit_msg[:50]}*"
    return old_text.rstrip() + mock_addition

def _infer_target_sections(changed_files: List[str]) -> List[str]:
    """변경된 파일 기반으로 업데이트할 섹션 추론"""
    targets = set()
    for f in changed_files:
        lf = f.lower()
        if any(x in lf for x in ['main','app','config']):
            targets.add('overview')
        if any(x in lf for x in ['router','endpoint','controller']):
            targets.add('architecture'); targets.add('modules')
        if any(x in lf for x in ['model','schema','entity']):
            targets.add('modules')
        if any(x in lf for x in ['service','handler']):
            targets.add('modules')
        if any(x in lf for x in ['test','spec']):
            targets.add('changelog')
    targets.add('changelog')  # 항상 changelog 포함
    return list(targets)

def _handle_partial_update(state: DocumentState, llm: Optional[ChatOpenAI], use_mock: bool) -> DocumentState:
    """섹션 단위 부분 업데이트 처리"""
    existing = state.get('existing_document') or {}
    content = existing.get('content', '')
    if not content:
        state['error'] = 'No existing document content for partial update'
        state['status'] = 'error'
        return state
    
    parsed = _parse_markdown_sections(content)
    
    file_summaries = state.get('file_change_summaries', [])
    analysis = state.get('analysis_result', '')
    changed_files = state.get('changed_files', []) or []
    commit_msg = (state.get('code_change') or {}).get('commit_message', '')
    target_sections = state.get('target_doc_sections') or _infer_target_sections(changed_files)
    
    max_chars = int(os.getenv('PARTIAL_DOC_UPDATE_MAX_SECTION_CHARS', '6000'))
    
    updates = []
    updated_map: Dict[str, str] = {}
    
    # LLM 초기화
    if not use_mock and llm is None:
        api_key = os.getenv('OPENAI_API_KEY') or ''
        if not api_key:
            use_mock = True
            print('[DocumentGenerator/Partial] No API key, using mock mode')
        else:
            llm = ChatOpenAI(model='gpt-4o-mini', temperature=0.2)
            print('[DocumentGenerator/Partial] LLM initialized')
    
    # 병렬 처리 활성화 여부 (섹션 수 >1 && 환경변수)
    max_workers = int(os.getenv('PARTIAL_UPDATE_MAX_CONCURRENCY', '3'))
    max_workers = max(1, max_workers)

    def _process_section(section_key: str) -> tuple[str, str, int, int, bool]:
        import time
        import threading
        thread_id = threading.current_thread().name
        start = time.time()
        print(f"  [{thread_id}] 시작: 섹션 '{section_key}' 업데이트")
        
        sec_old = parsed.sections.get(section_key, '')
        if not sec_old and section_key != 'changelog':
            sec_old = ''
        trimmed_old = sec_old[:max_chars] if len(sec_old) > max_chars else sec_old
        if use_mock:
            new_text_local = _update_section_mock(section_key, trimmed_old, commit_msg)
        else:
            # 스레드 안전을 위해 새 LLM 인스턴스를 생성 (모델명 동일)
            llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'gpt-4o-mini')) if llm else 'gpt-4o-mini'
            local_llm = llm if max_workers == 1 else ChatOpenAI(model=llm_model, temperature=0.2)
            new_text_local = _update_section_llm(section_key, trimmed_old, local_llm, file_summaries, analysis, commit_msg)
        changed_flag = new_text_local.strip() != sec_old.strip()
        
        elapsed = time.time() - start
        print(f"  [{thread_id}] 완료: 섹션 '{section_key}' ({elapsed:.2f}s, 변경={changed_flag})")
        return section_key, new_text_local, len(sec_old), len(new_text_local), changed_flag

    if len(target_sections) > 1 and max_workers > 1 and not use_mock:
        import time
        workers = min(max_workers, len(target_sections))
        print(f"[섹션 업데이트 병렬 처리] {len(target_sections)}개 섹션, {workers}개 워커 사용")
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_process_section, k): k for k in target_sections}
            for fut in as_completed(futures):
                k, new_text, old_len, new_len, changed_flag = fut.result()
                updated_map[k] = new_text
                updates.append({'key': k, 'old_length': old_len, 'new_length': new_len, 'changed': changed_flag})
        elapsed = time.time() - start_time
        print(f"[섹션 업데이트 병렬 완료] {elapsed:.2f}초 소요")
    else:
        # 순차 처리
        import time
        print(f"[섹션 업데이트 순차 처리] {len(target_sections)}개 섹션")
        start_time = time.time()
        for k in target_sections:
            k2, new_text, old_len, new_len, changed_flag = _process_section(k)
            updated_map[k2] = new_text
            updates.append({'key': k2, 'old_length': old_len, 'new_length': new_len, 'changed': changed_flag})
        elapsed = time.time() - start_time
        print(f"[섹션 업데이트 순차 완료] {elapsed:.2f}초 소요")
    
    # 섹션 병합
    merged_body = _merge_sections(parsed, updated_map)
    title = existing.get('title') or state.get('document_title') or 'Project Documentation'
    new_content = f"# {title}\n\n{merged_body}"
    
    state['document_content'] = new_content
    state['updated_sections'] = updates
    state['document_summary'] = f"Incremental update applied to sections: {', '.join(target_sections)}"
    state['status'] = 'saving'
    
    print(f"[DocumentGenerator/Partial] Updated {len(updates)} sections: {', '.join(target_sections)}")
    return state

def _env_partial_update_enabled() -> bool:
    return os.getenv("PARTIAL_DOC_UPDATE", "false").lower() in {"1","true","yes"}
