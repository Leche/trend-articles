# trend-articles — 프로젝트 메모리

트렌드림 다이제스트 기사 큐레이션/발행 레포.

## 📌 TODO: Anthropic API → 사내 AWS Bedrock 전환 (보류 중, 나중에 진행)

**배경**
- 현재 워크플로우의 클로드 호출은 **맥스플랜이 아니라** GitHub Actions 시크릿 `ANTHROPIC_API_KEY`(Anthropic Console, 토큰당 과금)로 동작함.
- 이 API 키 과금은 **개인 신용카드**에 청구됨.
- 맥스플랜(개인법카, 18일 종료)과 이 워크플로우는 **완전 별개** — 맥스플랜이 끝나도 워크플로우는 안 멈춤.
- 단, web_search를 안 써도 **기본 legacy 큐레이션이 매 실행마다 토큰을 쓰므로 개인카드 과금은 계속 발생**함.
- → 개인카드 과금을 끊으려면 사내 Bedrock으로 전환 필요. **현재는 보류, 다음에 진행 예정.**

**전환 시 변경 범위**
- 클라이언트 생성부 `anthropic.Anthropic()` → `anthropic.AnthropicBedrock()` (환경변수로 분기 권장):
  - `scripts/curate.py`: 약 505, 722, 994, 1243번 줄
  - `scripts/command.py`: 약 41, 92, 247번 줄
- 모델 ID → Bedrock inference profile 형식으로 매핑:
  - `claude-sonnet-4-6` → `us.anthropic.claude-sonnet-4-...`
  - `claude-haiku-4-5-20251001` → 대응 Bedrock ID
- 워크플로우 시크릿 교체:
  - `.github/workflows/curate.yml`(약 111줄), `command.yml`(약 37줄)의 `ANTHROPIC_API_KEY` → AWS 자격증명(액세스키 또는 GitHub OIDC role) + region
- 의존성: `anthropic` SDK는 그대로(Bedrock 클라이언트 내장), `boto3` 추가

**⚠️ 호환성 주의 — web_search 모드는 Bedrock 미지원**
- `curate.py:846` `curate_via_web_search()`는 Anthropic 서버사이드 `web_search_20250305` 툴 사용 → **Bedrock에서 동작 안 함.**
- 단, 이 모드는 `CURATE_MODE=web_search`로 **수동 지정 시에만** 동작. 스케줄 워크플로우는 `CURATE_MODE` 미설정 → 기본값 `legacy`(서버툴 미사용)로 돌므로 운영에는 영향 없음.
- 전환 시 web_search 모드 처리 방침(택1, 미정): (a) 그대로 두고 필요시 1st-party 키로만 사용 / (b) 외부 검색 API로 교체해 완전 Bedrock화 / (c) 모드 제거.
- 잠정 추천: 운영 경로(legacy + command.py)만 Bedrock 전환, web_search는 (a)로 보류.

## 큐레이션 모드 참고
- `CURATE_MODE=legacy` (기본): 화이트리스트 사이트 스캔(`scan_priority_sites`) + `curate_with_claude()`. 서버툴 미사용.
- `CURATE_MODE=web_search`: `curate_via_web_search()`, Anthropic web_search 서버툴 사용(Bedrock 불가).
- 스케줄은 외부 cron이 `workflow_dispatch` 호출 (GitHub Actions schedule 인덱싱 비결정성 회피).
