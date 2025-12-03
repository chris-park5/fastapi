from typing import Optional, Any, cast
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ..utils.llm_backoff import invoke_with_retry

from ..document_state import DocumentState


def change_analyzer_node(
    state: DocumentState,
    llm: Optional[ChatOpenAI] = None,
    use_mock: bool = False
) -> DocumentState:
    """
    변경사항 분석 노드
    
    역할:
        - Git diff를 분석하여 변경사항 요약 생성
        - Mock 모드: 템플릿 기반 분석
        - 실제 모드: LLM 기반 상세 분석
    """
    try:
        diff_content_raw = state.get("diff_content")
        diff_content = diff_content_raw if isinstance(diff_content_raw, str) else (diff_content_raw or "")
        changed_files = state.get("changed_files", []) or []
        code_change = state.get("code_change") or {}
        commit_message = code_change.get("commit_message", "") if isinstance(code_change, dict) else ""
        print(f"[ChangeAnalyzer] START | files={len(changed_files)} diff_len={len(diff_content)} mock={use_mock}")
        if changed_files:
            preview = ', '.join(changed_files[:6]) + (' ...' if len(changed_files) > 6 else '')
            print(f"[ChangeAnalyzer] Changed files: {preview}")
        
        # [수정됨] 파일별 변경사항 요약 생성 (개선된 로직 적용)
        file_change_summaries = _generate_file_summaries(changed_files, diff_content, use_mock, llm)
        print(f"[ChangeAnalyzer] Generated file summaries: {len(file_change_summaries)}")
        s = cast(Any, state)
        s["file_change_summaries"] = file_change_summaries
        
        if use_mock:
            print("[ChangeAnalyzer] PATH=MOCK (LLM bypass)")
            # Mock 응답 + 타겟 섹션 추론
            line_adds = diff_content.count('+') if diff_content else 0
            analysis = (
                "## 주요 변경사항\n"
                f"- 파일 수정: {', '.join(changed_files)}\n"
                f"- 커밋 메시지: {commit_message}\n\n"
                "## 변경 이유\n코드 개선 및 기능 추가를 위한 변경\n\n"
                "## 영향 범위\n수정된 파일들의 관련 기능에 영향\n\n"
                "## 기술적 세부사항\n"
                f"- 추가/수정 라인(+): {line_adds}\n"
            )
            state["analysis_result"] = analysis
            state["target_doc_sections"] = _identify_target_sections(changed_files)
            state["status"] = "generating"
            return state
        
        # 실제 LLM 분석 (종합 분석)
        if llm is None:
            raise ValueError("LLM is required for non-mock mode")
        print("[ChangeAnalyzer] PATH=REAL LLM")
        
        system_prompt = (
            "당신은 코드 변경사항을 분석하여 '문서 업데이트가 필요한 섹션'을 식별하는 전문가입니다.\n"
            "반드시 다음 JSON 스키마로만 출력하세요 (추가 텍스트, 마크다운 헤더, 주석 금지):\n\n"
            "{\n"
            "  \"summary\": [\"변경 요약 1-2문장\", \"...\"],\n"
            "  \"reasons\": [\"변경 이유 요약\"],\n"
            "  \"impact\": [\"모듈/레이어 영향\"],\n"
            "  \"details\": [\"라이브러리/패턴 등 기술적 세부사항\"],\n"
            "  \"section_targets\": [\"overview|architecture|modules|changelog 중 해당 키들\"]\n"
            "}\n\n"
            "규칙:\n"
            "- JSON 이외의 어떤 텍스트도 출력하지 마세요.\n"
            "- section_targets 는 소문자 키만 사용.\n"
            "- 불필요한 추측은 피하고 diff 기반으로 판단.\n"
        )

        user_prompt = f"""커밋 메시지: {commit_message}

변경된 파일들:
{', '.join(changed_files)}

Git Diff:
{diff_content}

위 코드 변경사항을 분석하여 요약해주세요."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        # 레이트리밋 대비 재시도 래퍼 사용
        print("[ChangeAnalyzer] Invoking LLM for aggregate analysis ...")
        response = invoke_with_retry(llm, messages)

        raw_content = getattr(response, 'content', response)
        if isinstance(raw_content, list):
            analysis_text = "\n".join(str(c) for c in raw_content)
        else:
            analysis_text = str(raw_content)

        # JSON 파싱 시도
        import json
        analysis_json = None
        try:
            analysis_json = json.loads(analysis_text)
            print("[ChangeAnalyzer] JSON parse: SUCCESS")
        except Exception as parse_err:
            analysis_json = None
            print(f"[ChangeAnalyzer] JSON parse: FAIL | {str(parse_err)[:100]}")

        # 상태 저장
        if analysis_json:
            s_any = cast(Any, state)
            s_any["analysis_json"] = analysis_json
            sections = analysis_json.get("section_targets") if isinstance(analysis_json, dict) else None
            if isinstance(sections, list):
                allowed = {"overview", "architecture", "modules", "changelog"}
                targets = [str(x).strip().lower() for x in sections if str(x).strip().lower() in allowed]
                state["target_doc_sections"] = targets
                print(f"[ChangeAnalyzer] Targets(from JSON): {targets}")
            
            summary_md = []
            for key in ("summary","reasons","impact","details"):
                val = analysis_json.get(key)
                if isinstance(val, list) and val:
                    summary_md.append(f"## {key}\n- " + "\n- ".join(str(v) for v in val))
            state["analysis_result"] = "\n\n".join(summary_md)
        else:
            state["analysis_result"] = analysis_text
            extracted = _extract_section_targets(analysis_text)
            state["target_doc_sections"] = extracted
            print(f"[ChangeAnalyzer] Targets(fallback): {extracted}")
            
        state["status"] = "generating"
        print("[ChangeAnalyzer] END | status=generating")
        return state
        
    except Exception as e:
        state["error"] = f"Change analyzer failed: {str(e)}"
        state["status"] = "error"
        print(f"[ChangeAnalyzer] ERROR | {e}")
        return state


def _extract_section_targets(text: str) -> list[str]:
    """LLM 응답 문자열에서 SECTION_TARGETS 값을 파싱"""
    m = re.search(r'section_targets:\s*([a-z,\s]+?)(?:\n|$)', text.lower(), re.MULTILINE | re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1).strip()
    raw = re.sub(r'\s+', ' ', raw)
    tokens = [x.strip() for x in raw.split(',') if x.strip()]
    allowed = {"overview", "architecture", "modules", "changelog"}
    return [t for t in tokens if t in allowed]


def _identify_target_sections(changed_files: list[str]) -> list[str]:
    """파일명 기반 타겟 섹션 추론"""
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
    targets.add('changelog')
    return list(targets)


def _detect_change_type(file_diff: str) -> str:
    """파일별 diff 기반 변경 타입 판별"""
    if not file_diff:
        return "modified" # diff가 없어도 일단 modified로 처리
    if "+++ /dev/null" in file_diff:
        return "deleted"
    if "--- /dev/null" in file_diff:
        return "added"
    return "modified"


def _build_prompt(file: str, file_diff: str) -> str:
    """파일 단위 변경 요약 프롬프트"""
    changed = []
    for line in file_diff.split("\n"):
        if line.startswith("+") or line.startswith("-"):
            changed.append(line)
        if len(changed) > 120:
            break

    diff_excerpt = "\n".join(changed[:120])
    return (
        f"다음 파일의 변경사항을 1-2문장으로 요약하세요.\n"
        f"파일: {file}\n\n"
        f"변경된 핵심 라인:\n{diff_excerpt[:1500]}\n\n"
        f"요약:"
    )


# =========================================================
# [New] Diff 파싱 및 매칭 로직 (기존 _extract_file_diff 대체)
# =========================================================

def _parse_diff_to_map(diff_content: str) -> dict[str, str]:
    """
    전체 Diff 내용을 파일별로 쪼개어 {파일명(a/경로): diff블록} 맵으로 반환.
    정규식보다 훨씬 안정적임.
    """
    if not diff_content:
        return {}
        
    diff_map = {}
    # 'diff --git ' 기준으로 나눔. 첫 번째 청크는 보통 비어있거나 헤더.
    chunks = diff_content.split('diff --git ')
    
    for chunk in chunks:
        if not chunk.strip():
            continue
            
        # chunk의 첫 줄에서 파일 경로 추출 (a/path/to/file b/path/to/file)
        # 보통 "a/..." 가 원본 파일 경로
        lines = chunk.split('\n', 1)
        header_line = lines[0]
        
        # a/경로 추출 시도
        match = re.search(r'a/(.*?)\s+b/', header_line)
        if match:
            file_path = match.group(1).strip()
            # "diff --git " 접두사를 다시 붙여서 저장
            diff_map[file_path] = f"diff --git {chunk}"
        else:
            # a/ b/ 패턴이 아닐 경우(예: --no-prefix), 파일명만이라도 키로 잡기 위해 단순 처리 가능
            # 여기서는 안전하게 첫 단어를 키로 사용
            parts = header_line.split()
            if len(parts) >= 2:
                # 대략 a/file 형태라고 가정
                f = parts[0]
                if f.startswith("a/"): f = f[2:]
                diff_map[f] = f"diff --git {chunk}"

    return diff_map


def _find_diff_for_file(filename: str, diff_map: dict[str, str]) -> str:
    """
    changed_files의 filename과 diff_map의 키(a/경로)를 매칭.
    경로 불일치(예: src/main.py vs a/backend/src/main.py)를 해결하기 위해 Suffix 매칭 사용.
    """
    # 1. 완전 일치 (Best)
    if filename in diff_map:
        return diff_map[filename]
    
    # 2. 키가 "a/..." 형태가 아니라면 filename 그대로 키 조회
    if f"a/{filename}" in diff_map:
        return diff_map[f"a/{filename}"]

    # 3. Suffix 매칭 (Flexible)
    # filename이 "main.py"이고 map key가 "backend/main.py"인 경우 등
    norm_name = filename.strip().replace('\\', '/')
    for key, content in diff_map.items():
        # diff map의 키는 보통 전체 경로.
        # 입력된 filename이 diff map 키의 뒷부분과 일치하면 매칭으로 간주
        if key.endswith(norm_name) or norm_name.endswith(key):
            return content
            
    return ""


def _generate_file_summaries(
    changed_files: list[str],
    diff_content: str,
    use_mock: bool,
    llm: Optional[ChatOpenAI]
) -> list[dict]:
    """파일별 변경사항 요약 생성 (Diff 파싱 방식 개선)."""

    summaries: list[dict] = []
    
    # [Fix] Diff를 미리 파싱하여 Map으로 변환
    diff_map = _parse_diff_to_map(diff_content)

    # 1) Mock 모드
    if use_mock:
        for file in changed_files:
            file_diff = _find_diff_for_file(file, diff_map)
            change_type = _detect_change_type(file_diff)
            summaries.append({
                "file": file,
                "change_type": change_type,
                "summary": f"{file} 파일이 {change_type}되었습니다.",
                "priority": _get_file_priority(file)
            })
        return summaries

    # 2) LLM 없음 (Fallback)
    if llm is None:
        for f in changed_files:
            file_diff = _find_diff_for_file(f, diff_map)
            summaries.append({
                "file": f,
                "change_type": _detect_change_type(file_diff),
                "summary": f"{f} 파일 변경",
                "priority": _get_file_priority(f)
            })
        return summaries

    # 3) 우선순위 분류
    high_medium = []
    for f in changed_files:
        p = _get_file_priority(f)
        if p == "low":
            file_diff = _find_diff_for_file(f, diff_map)
            change_type = _detect_change_type(file_diff)
            summaries.append({
                "file": f,
                "change_type": change_type,
                "summary": f"{f} ({change_type})",
                "priority": p
            })
        else:
            high_medium.append((f, p))

    max_workers = int(os.getenv("FILE_SUMMARY_MAX_CONCURRENCY", "4"))
    max_workers = max(1, max_workers)

    # 4) LLM 처리 함수 (내부 함수에서 diff_map 참조)
    def _summarize(file: str, priority: str) -> dict:
        import time
        import threading
        thread_id = threading.current_thread().name
        start = time.time()
        
        # [Fix] 맵에서 Diff 검색
        file_diff = _find_diff_for_file(file, diff_map)
        change_type = _detect_change_type(file_diff)

        # Diff가 정말 없으면 분석 불가 -> Fallback
        if not file_diff:
            # 디버깅용: 실제로는 로그를 남기는 것이 좋음
            # print(f"[{thread_id}] Warn: No diff found for {file}")
            return {
                "file": file,
                "change_type": change_type,
                "summary": f"{file} 변경 (Diff 상세 없음)",
                "priority": priority
            }

        prompt = _build_prompt(file, file_diff)
        text = ""
        try:
            resp = invoke_with_retry(llm, [HumanMessage(content=prompt)])
            text = str(getattr(resp, "content", resp))
        except Exception as e:
            text = f"{file} 파일 {change_type} (분석 실패)"

        print(f"  [{thread_id}] 완료: {file} ({time.time()-start:.2f}s)")
        return {
            "file": file,
            "change_type": change_type,
            "summary": text,
            "priority": priority
        }

    # 5) 병렬 실행
    if high_medium:
        workers = min(max_workers, len(high_medium))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_summarize, f, p): (f, p) for f, p in high_medium}
            for fut in as_completed(futures):
                summaries.append(fut.result())

    # 6) 순서 복원
    order_map = {s["file"]: s for s in summaries}
    return [order_map[f] for f in changed_files if f in order_map]


def _get_file_priority(filepath: str) -> str:
    """파일 우선순위 판단"""
    lower = filepath.lower()
    
    if any(x in lower for x in ['router', 'endpoint', 'controller', 'api']): return "high"
    if any(x in lower for x in ['schema', 'model', 'entity']): return "high"
    if any(x in lower for x in ['service', 'handler', 'manager']): return "high"
    if any(x in lower for x in ['auth', 'security', 'permission']): return "high"
    if any(x in lower for x in ['database', 'migration', 'config']): return "high"
    
    if any(x in lower for x in ['util', 'helper', 'middleware']): return "medium"
    if any(x in lower for x in ['test', 'spec']): return "medium"
    
    return "low"
