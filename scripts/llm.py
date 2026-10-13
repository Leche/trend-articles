#!/usr/bin/env python3
"""
트렌드림 모델 호출 백엔드 — curate.py 와 command.py 가 같이 쓴다 (2026-10-13).
LLM_BACKEND=api : Anthropic API (ANTHROPIC_API_KEY, 사비 과금)
LLM_BACKEND=cli : 러너에 깐 Claude Code 를 `claude -p` 로 불러 리체 팀플랜 토큰(CLAUDE_CODE_OAUTH_TOKEN)으로 돈다.
"""
import os
import json

try:
    import anthropic
except ImportError:  # cli 백엔드에선 없어도 된다
    anthropic = None

# 5.5 는 안전 분류기가 넓어 AI 뉴스 요약에서 오탐 거절이 날 수 있다. API 백엔드에선 거절 시 서버가
# Anthropic 추천 모델로 한 번 더 돌린다 (CLI 백엔드엔 없음).
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

# ─── 모델 호출 백엔드 (2026-10-13) ───────────────────────────
# LLM_BACKEND=api : Anthropic API (ANTHROPIC_API_KEY, 사비 과금) — 기본값
# LLM_BACKEND=cli : GitHub Actions 러너에 깐 Claude Code 를 `claude -p` 로 불러 리체 팀플랜 토큰
#                   (CLAUDE_CODE_OAUTH_TOKEN, `claude setup-token`)으로 돈다. API 과금 없음.
#                   공식 문서: "OAuth 토큰으로 인증하면 API 과금 대신 구독을 쓴다" (Pro·Max·Team·Enterprise).
# 호출 모양은 같다 — 모델·effort·JSON 스키마를 그대로 넘기고, 응답도 content/stop_reason/usage 를 흉내 낸
# 객체로 돌려줘서 호출부가 백엔드를 모른다. CLI 에 없는 것: max_tokens(무시), 서버 측 거절 재시도(FALLBACK).
# ⚠️ CLI 백엔드일 때 ANTHROPIC_API_KEY 가 환경에 있으면 그 키가 우선돼 API 로 과금된다 — curate.yml 이 cli 모드에선
#   키를 아예 안 넘긴다. --bare 는 OAuth 토큰을 안 읽으므로 쓰지 않는다.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "api").strip().lower()
CLI_TIMEOUT_SEC = int(os.environ.get("CLI_TIMEOUT_SEC", "900"))


class _CliBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _CliUsage:
    def __init__(self, u):
        u = u or {}
        self.input_tokens = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                            + (u.get("cache_read_input_tokens") or 0)
        self.output_tokens = u.get("output_tokens") or 0


class _CliResponse:
    """claude -p --output-format json 결과를 API 응답처럼 보이게 감싼 것."""
    def __init__(self, data, model):
        structured = data.get("structured_output")
        text = json.dumps(structured, ensure_ascii=False) if structured is not None else (data.get("result") or "")
        self.content = [_CliBlock(text)] if text else []
        self.stop_reason = "refusal" if data.get("is_error") else (data.get("stop_reason") or "end_turn")
        self.stop_details = data.get("result") if data.get("is_error") else None
        self.usage = _CliUsage(data.get("usage"))
        self.model = model
        self.api_equiv_usd = data.get("total_cost_usd")


def _cli_create(**kwargs):
    import subprocess
    model = kwargs["model"]
    oc = kwargs.get("output_config") or {}
    effort = oc.get("effort") or "low"
    schema = (oc.get("format") or {}).get("schema") if isinstance(oc.get("format"), dict) else None
    prompt = kwargs["messages"][0]["content"]
    # tools=["WebSearch","WebFetch"] 처럼 주면 그 도구만 켠다(웹 발굴용). 기본은 도구 없음.
    tools = kwargs.get("tools") or []
    timeout = kwargs.get("timeout") or CLI_TIMEOUT_SEC
    cmd = ["claude", "-p", "--no-session-persistence", "--disable-slash-commands",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--tools", ",".join(tools), "--permission-mode", "dontAsk",
           "--model", model, "--effort", effort, "--output-format", "json"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if kwargs.get("max_turns"):
        cmd += ["--max-turns", str(kwargs["max_turns"])]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    if kwargs.get("system"):
        cmd += ["--system-prompt", kwargs["system"]]
    last_err = None
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last_err = f"timeout {timeout}s"
            print(f"   ⏱  claude -p 타임아웃 (시도 {attempt + 1}/3)")
            continue
        if r.returncode != 0 or not r.stdout.strip():
            last_err = (r.stderr or r.stdout or "").strip()[-500:]
            print(f"   ⚠️  claude -p 실패 rc={r.returncode} (시도 {attempt + 1}/3): {last_err[:200]}")
            continue
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            last_err = "출력이 JSON 이 아님: " + r.stdout[:200]
            print(f"   ⚠️  {last_err}")
            continue
        resp = _CliResponse(data, model)
        if schema and not data.get("structured_output"):
            last_err = "structured_output 없음: " + str(data.get("result"))[:200]
            print(f"   ⚠️  {last_err} (시도 {attempt + 1}/3)")
            if data.get("is_error"):
                return resp  # 거절 등 — 호출부가 stop_reason 으로 처리
            continue
        return resp
    raise RuntimeError(f"claude -p 3회 실패: {last_err}")


def client():
    """API 백엔드일 때만 진짜 클라이언트. cli 백엔드에선 None (키가 없어도 뜨게)."""
    if LLM_BACKEND == "cli" or anthropic is None:
        return None
    return anthropic.Anthropic(max_retries=8)


def create(client, **kwargs):
    """messages.create + 거절 시 서버 측 재시도(FALLBACK). 모든 큐레이션 호출은 이걸로 부른다.
    LLM_BACKEND=cli 면 client 를 쓰지 않고 claude -p 로 돈다."""
    if LLM_BACKEND == "cli":
        return _cli_create(**kwargs)
    for k in ("tools", "max_turns", "timeout"):  # CLI 전용 옵션 — API 엔 없다
        kwargs.pop(k, None)
    return client.beta.messages.create(**FALLBACK, **kwargs)


def log_usage(label, response):
    """호출별 토큰 사용량을 로그에 남긴다 (입력 · 출력 · 모델)."""
    try:
        u = response.usage
        equiv = getattr(response, "api_equiv_usd", None)
        tail = f", API 환산 ${equiv:.3f}, 팀플랜 과금" if equiv is not None else ""
        print(f"   📊 {label}: 입력 {u.input_tokens:,} · 출력 {u.output_tokens:,} 토큰 ({response.model}{tail})")
    except Exception:
        pass
    if getattr(response, "stop_reason", None) == "refusal":
        print(f"   🚫 {label}: 거절됨 (재시도 모델까지) — {getattr(response, 'stop_details', None)}")
    elif any(getattr(b, "type", None) == "fallback" for b in getattr(response, "content", []) or []):
        print(f"   ↪️  {label}: 거절돼서 {response.model} 로 재시도해 받음")


