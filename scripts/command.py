#!/usr/bin/env python3
"""
자연어 명령을 Claude API로 해석하고 트렌드림 HTML을 직접 수정하는 스크립트
- 링크 수정: "5번 기사 링크를 https://... 로 바꿔줘"
- 순서 조정: "3번 기사를 1번으로 이동해줘"
- 자유 편집: "1번 기사 제목을 '새 제목'으로 바꿔줘" / "trigger.html 카드 설명 수정"
"""

import os
import re
import sys
import json
import datetime
import anthropic
import requests
from bs4 import BeautifulSoup

# ─── 환경 변수 ───────────────────────────────────────────────
COMMAND_PROMPT = os.environ.get("COMMAND_PROMPT", "").strip()
TARGET_DATE    = os.environ.get("TARGET_DATE", "").strip()

KST   = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()

if TARGET_DATE:
    try:
        date_obj = datetime.datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()
    except ValueError:
        date_obj = TODAY
else:
    date_obj = TODAY

DATE_DIR = date_obj.strftime("%Y-%m-%d")

print(f"📅 대상 날짜: {DATE_DIR}")
print(f"📝 명령: {COMMAND_PROMPT}")


# ─── Claude로 명령 해석 ───────────────────────────────────────
def interpret_command(prompt: str) -> dict:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system="""당신은 트렌드림 기사 큐레이션 관리 도구의 명령 해석기입니다.
사용자의 자연어 요청을 분석하여 아래 JSON 형식 중 하나로만 응답하세요.

지원하는 액션:
1. 링크 수정 (LINK 박스의 URL 변경):
   {"action": "fix_link", "items": [{"num": 5, "url": "https://..."}]}

2. 기사 순서 변경 (기사 위치 이동 + ARTICLE 번호 재부여):
   {"action": "reorder", "items": [{"from": 3, "to": 1}]}

3. index.html 기사 내용 자유 수정 (제목, 한 줄 요약, 3줄 요약 등):
   {"action": "free_edit", "file": "index.html", "article_num": 3, "instruction": "원본 지시 그대로"}
   - article_num: 수정할 기사 번호 (모든 기사면 0)
   - 예: "1번 기사 제목을 '새 제목'으로 바꿔줘" → article_num: 1

4. trigger.html 자유 수정 (카드 제목, 설명, 버튼, 라벨, h1, subtitle 등 모든 요소):
   {"action": "free_edit", "file": "trigger.html", "instruction": "원본 지시 그대로"}
   - trigger.html 관련 요청은 항상 이 액션 사용
   - trigger-test.html은 자동 동기화되므로 별도 처리 불필요. trigger-test.html 언급이 있어도 trigger.html만 대상으로 JSON 1개만 출력

5. 원본 기사와 비교해 다이제스트 교정 (제목·요약을 원본 기준으로 맞춤):
   {"action": "sync_with_source", "article_num": 1, "instruction": "원본 지시 그대로"}
   - "원본과 다르다", "원본 기사 제목 가져와줘", "원본 기준으로 맞춰줘", "원문과 안 맞아" 등 원본 대조·교정이 필요한 요청
   - article_num: 대상 기사 번호 (1 이상 필수)

이해할 수 없는 요청:
   {"action": "unknown", "message": "이해할 수 없는 이유 간단히"}

JSON만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.""",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'\{[\s\S]*?\}', raw)
    if not m:
        raise ValueError(f"Claude 응답 파싱 실패: {raw}")
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        # 중첩 객체가 있을 수 있으므로 raw_decode 사용
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(raw[raw.index('{'):])
        return obj


# ─── AI 변경 식별 ─────────────────────────────────────────────
def ai_identify_changes(context_html: str, instruction: str) -> list:
    """HTML 섹션과 지시를 받아 [{old, new}] 변경 쌍 반환"""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system="""당신은 HTML 텍스트 편집 도우미입니다.
주어진 HTML에서 지시에 따라 변경할 텍스트를 찾아 JSON 배열로만 응답하세요.

응답 형식: [{"old": "정확한 기존 텍스트", "new": "새 텍스트"}]

규칙:
- "old"는 HTML 내에서 찾을 수 있는 정확한 텍스트 (태그 내부 텍스트 그대로)
- HTML 구조(태그, 속성, 클래스)는 절대 변경하지 마세요
- src="[IMAGE]" 플레이스홀더는 무시하세요
- JSON 배열만 출력, 다른 설명 없이""",
        messages=[{"role": "user", "content": f"지시: {instruction}\n\nHTML:\n{context_html}"}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'\[[\s\S]*\]', raw)
    if not m:
        raise ValueError(f"변경 사항 파싱 실패: {raw}")
    return json.loads(m.group())


def apply_changes(html: str, changes: list) -> str:
    """[{old, new}] 변경 사항을 HTML에 적용"""
    for change in changes:
        old_text = change.get("old", "").strip()
        new_text = change.get("new", "").strip()
        if not old_text:
            continue
        if old_text not in html:
            raise ValueError(f"텍스트를 찾을 수 없어요: '{old_text[:80]}'")
        html = html.replace(old_text, new_text, 1)
        print(f"  ✅ '{old_text[:50]}' → '{new_text[:50]}'")
    return html


# ─── HTML 수정 유틸 ───────────────────────────────────────────
def fix_link_in_html(html: str, num: int, new_url: str) -> str:
    """ARTICLE XX 이후의 article-link href + 텍스트 교체"""
    num_str   = str(num).zfill(2)
    label_idx = html.find(f"ARTICLE {num_str}")
    if label_idx == -1:
        raise ValueError(f"기사 {num}번을 찾을 수 없어요.")

    link_cls_idx = html.find('class="article-link"', label_idx)
    if link_cls_idx == -1:
        raise ValueError("링크 영역을 찾을 수 없어요.")

    a_start  = html.rfind("<a", 0, link_cls_idx)
    a_end    = html.find("</a>", link_cls_idx) + 4
    old_a    = html[a_start:a_end]

    href_m = re.search(r'href="([^"]+)"', old_a)
    if not href_m:
        raise ValueError("href를 찾을 수 없어요.")
    old_url = href_m.group(1)

    new_a = old_a.replace(f'href="{old_url}"', f'href="{new_url}"')
    new_a = new_a.replace(f">{old_url}<", f">{new_url}<")
    return html[:a_start] + new_a + html[a_end:]


def find_article_blocks(html: str):
    """article-card div를 depth tracking으로 추출 → [(start, end), ...]"""
    marker = '<div class="article-card">'
    blocks = []
    pos    = 0
    while True:
        start = html.find(marker, pos)
        if start == -1:
            break
        depth = 1
        cur   = start + len(marker)
        while depth > 0 and cur < len(html):
            next_open  = html.find("<div", cur)
            next_close = html.find("</div>", cur)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                cur = next_open + 4
            else:
                depth -= 1
                cur = next_close + 6
        blocks.append((start, cur))
        pos = cur
    return blocks


def reorder_in_html(html: str, from_num: int, to_num: int) -> str:
    """기사 블록 순서 변경 + ARTICLE 번호 재부여"""
    spans  = find_article_blocks(html)
    total  = len(spans)
    if total == 0:
        raise ValueError("기사 블록을 찾을 수 없어요.")
    if from_num < 1 or from_num > total or to_num < 1 or to_num > total:
        raise ValueError(f"유효 범위(1~{total})를 벗어난 번호예요.")

    blocks = [html[s:e] for s, e in spans]
    prefix = html[: spans[0][0]]
    suffix = html[spans[-1][1] :]

    # 이동
    block = blocks.pop(from_num - 1)
    blocks.insert(to_num - 1, block)

    # ARTICLE 번호 재부여
    renumbered = []
    for i, b in enumerate(blocks):
        b = re.sub(r"ARTICLE \d{2}", f"ARTICLE {str(i + 1).zfill(2)}", b)
        renumbered.append(b)

    return prefix + "".join(renumbered) + suffix


def get_article_source_url(article_section: str) -> str:
    """article 섹션 안의 article-link href 추출"""
    m = (re.search(r'class="article-link"[^>]*href="(https?://[^"]+)"', article_section)
         or re.search(r'href="(https?://[^"]+)"[^>]*class="article-link"', article_section)
         or re.search(r'href="(https?://[^"]+)"', article_section))
    return m.group(1) if m else ""


def fetch_source_article(url: str) -> dict:
    """원본 기사 URL을 fetch해서 제목·본문 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ko,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "twitter:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    body_tag = soup.find("article") or soup.find("main") or soup.find("body")
    body_text = body_tag.get_text(separator="\n", strip=True) if body_tag else ""
    if len(body_text) > 8000:
        body_text = body_text[:8000] + "\n...[잘림]"
    return {"title": title, "body": body_text, "url": url}


def ai_sync_with_source(article_section: str, source: dict, instruction: str) -> list:
    """원본 기사와 다이제스트 섹션을 받아 [{old, new}] 교정 쌍 반환"""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="""당신은 트렌드림 다이제스트 편집 도우미입니다.
원본 기사와 현재 다이제스트의 해당 기사 섹션을 받아, 원본 기준으로 어긋난 부분을
[{"old":"정확한 기존 텍스트","new":"새 텍스트"}] JSON 배열로만 출력하세요.

규칙:
- 제목(article-title), 1줄 요약(article-summary), 3줄 요약(bullet-item) 모두 원본 기준으로 정확하게 맞추세요
- "old"는 다이제스트 HTML 안에 그대로 존재하는 텍스트 (태그 안의 텍스트만, 태그 자체는 포함하지 말 것)
- "new"는 원본에 부합하는 새 텍스트
- HTML 구조·태그·클래스는 절대 변경하지 마세요
- 다이제스트 어투(존댓말 + "~요" 종결)는 유지하세요
- 변경 필요 없으면 빈 배열 []
- JSON 배열만 출력, 다른 설명 없이""",
        messages=[{"role": "user", "content": (
            f"지시: {instruction}\n\n"
            f"[원본 기사 URL] {source['url']}\n"
            f"[원본 기사 제목]\n{source['title']}\n\n"
            f"[원본 기사 본문]\n{source['body']}\n\n"
            f"[현재 다이제스트 섹션]\n{article_section}"
        )}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'\[[\s\S]*\]', raw)
    if not m:
        raise ValueError(f"sync 응답 파싱 실패: {raw}")
    return json.loads(m.group())


def get_article_section(html: str, num: int) -> tuple:
    """특정 기사 article 블록 추출 (base64 이미지 제거) → (stripped_section, start, end)"""
    num_str = str(num).zfill(2)
    label_pos = html.find(f"ARTICLE {num_str}")
    if label_pos == -1:
        raise ValueError(f"기사 {num}번을 찾을 수 없어요.")

    # <article 태그 시작점 (label 이전)
    article_start = html.rfind("<article", 0, label_pos)
    if article_start == -1:
        raise ValueError(f"기사 {num}번 article 태그를 찾을 수 없어요.")

    # </article> 끝점
    article_end = html.find("</article>", article_start) + len("</article>")

    section = html[article_start:article_end]
    # base64 이미지 제거 (플레이스홀더로 교체)
    stripped = re.sub(r'src="data:[^"]*"', 'src="[IMAGE]"', section)

    return stripped, article_start, article_end


# ─── trigger-test.html 자동 동기화 ─────────────────────────────
# trigger.html 수정 시 trigger-test.html에도 동일하게 반영
# 단, TEST 전용 패치 6개는 유지
TEST_PATCHES = [
    # (trigger.html 원본 텍스트, trigger-test.html 텍스트)
    ("<title>트렌드림 컨트롤러 컨트롤</title>",
     "<title>트렌드림 컨트롤러 컨트롤 [TEST]</title>"),
    ('<p class="subtitle">모바일에서 간편하게 아티클들을 컨트롤 하세요</p>',
     '<p class="subtitle" style="color:#CF3030;">🧪 테스트 모드 — test/ 폴더에서 동작합니다</p>'),
    ("// ── 오늘 KST 날짜 ──\nfunction getTodayKST() {\n  const now = new Date();\n  const kst = new Date(now.getTime() + 9 * 60 * 60 * 1000);\n  return kst.toISOString().split('T')[0];",
     "// ── 테스트 모드: 날짜 대신 \"test\" 고정 경로 사용 ──\nfunction getTodayKST() {\n  return 'test';"),
    ("replace_urls: parts.join(',') })",
     "replace_urls: parts.join(','), test_mode: 'true' })"),
    ("showStatus('replaceStatus', 'success', `기사 교체 시작! (${parts.length}개 교체) 카카오워크로 완료 알림이 올 거예요.`)",
     "showStatus('replaceStatus', 'success', `🧪 [TEST] 기사 교체 시작! (${parts.length}개) test/index.html에 반영돼요.`)"),
]


def sync_trigger_test():
    """trigger.html → trigger-test.html 동기화 (TEST 패치 유지)"""
    if not os.path.exists("trigger.html"):
        print("  ⚠️  trigger.html 없음 — 동기화 건너뜀")
        return
    html = read_html("trigger.html")
    for original, test_ver in TEST_PATCHES:
        html = html.replace(original, test_ver)
    write_html("trigger-test.html", html)
    print("  🔄 trigger-test.html 자동 동기화 완료")


# ─── 파일 읽기/쓰기 ───────────────────────────────────────────
def read_html(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"파일 없음: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_html(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ 저장 완료: {path}")


# ─── 메인 ─────────────────────────────────────────────────────
def main():
    if not COMMAND_PROMPT:
        print("❌ COMMAND_PROMPT가 비어 있어요.")
        sys.exit(1)

    # 1. Claude로 명령 해석
    print("\n🤖 명령 해석 중...")
    try:
        result = interpret_command(COMMAND_PROMPT)
    except Exception as e:
        print(f"❌ 해석 실패: {e}")
        sys.exit(1)

    print(f"🔍 해석 결과: {json.dumps(result, ensure_ascii=False)}")
    action = result.get("action")

    # 2. 대상 파일 경로
    date_path = f"{DATE_DIR}/index.html"
    root_path = "index.html"

    # 3. 액션 실행
    if action == "fix_link":
        items = result.get("items", [])
        for item in items:
            num     = item["num"]
            new_url = item["url"]
            print(f"\n🔗 링크 수정: {num}번 → {new_url}")
            for path in [date_path, root_path]:
                try:
                    html = read_html(path)
                    html = fix_link_in_html(html, num, new_url)
                    write_html(path, html)
                except FileNotFoundError:
                    print(f"  ⚠️  {path} 없음 — 건너뜀")
                except Exception as e:
                    print(f"  ❌ {path} 수정 실패: {e}")
                    sys.exit(1)

    elif action == "reorder":
        items = result.get("items", [])
        for item in items:
            from_num = item["from"]
            to_num   = item["to"]
            print(f"\n🔀 순서 조정: {from_num}번 → {to_num}번")
            for path in [date_path, root_path]:
                try:
                    html = read_html(path)
                    html = reorder_in_html(html, from_num, to_num)
                    write_html(path, html)
                except FileNotFoundError:
                    print(f"  ⚠️  {path} 없음 — 건너뜀")
                except Exception as e:
                    print(f"  ❌ {path} 수정 실패: {e}")
                    sys.exit(1)

    elif action == "free_edit":
        file_target = result.get("file", "index.html")
        instruction = result.get("instruction", COMMAND_PROMPT)
        article_num = result.get("article_num", 0)

        print(f"\n✏️  자유 편집: [{file_target}] '{instruction}'")

        if file_target == "trigger.html":
            # trigger.html 전체 전송 (37KB, 관리 가능)
            try:
                html = read_html("trigger.html")
                print("  🤖 변경 사항 식별 중...")
                changes = ai_identify_changes(html, instruction)
                print(f"  📋 변경 항목 {len(changes)}개")
                html = apply_changes(html, changes)
                write_html("trigger.html", html)
                sync_trigger_test()
            except FileNotFoundError:
                print("  ⚠️  trigger.html 없음 — 건너뜀")
            except Exception as e:
                print(f"  ❌ trigger.html 수정 실패: {e}")
                sys.exit(1)

        else:
            # index.html: 특정 기사 블록만 추출해서 전송
            for path in [date_path, root_path]:
                try:
                    html = read_html(path)

                    if article_num and article_num > 0:
                        # 특정 기사 섹션만 추출
                        stripped_section, art_start, art_end = get_article_section(html, article_num)
                        print(f"  🤖 {article_num}번 기사 섹션 변경 사항 식별 중...")
                        changes = ai_identify_changes(stripped_section, instruction)
                        print(f"  📋 변경 항목 {len(changes)}개")
                        # 전체 HTML에 적용 (base64 이미지가 있는 원본에 적용)
                        html = apply_changes(html, changes)
                    else:
                        # 전체 기사 대상 (base64 제거 후 전체 전송)
                        stripped = re.sub(r'src="data:[^"]*"', 'src="[IMAGE]"', html)
                        print("  🤖 전체 기사 변경 사항 식별 중...")
                        changes = ai_identify_changes(stripped, instruction)
                        print(f"  📋 변경 항목 {len(changes)}개")
                        html = apply_changes(html, changes)

                    write_html(path, html)
                except FileNotFoundError:
                    print(f"  ⚠️  {path} 없음 — 건너뜀")
                except Exception as e:
                    print(f"  ❌ {path} 수정 실패: {e}")
                    sys.exit(1)

    elif action == "sync_with_source":
        article_num = result.get("article_num", 0)
        instruction = result.get("instruction", COMMAND_PROMPT)
        if not article_num or article_num < 1:
            print("⚠️  sync_with_source: article_num이 필요해요 (예: '1번 기사 원본과 맞춰줘').")
            sys.exit(0)
        print(f"\n🔄 원본 기준 교정: {article_num}번 기사")
        for path in [date_path, root_path]:
            try:
                html = read_html(path)
                stripped_section, _, _ = get_article_section(html, article_num)
                src_url = get_article_source_url(stripped_section)
                if not src_url:
                    print(f"  ⚠️  {path}: {article_num}번 원본 URL 못 찾음 — 건너뜀")
                    continue
                print(f"  🌐 원본 fetch: {src_url}")
                source = fetch_source_article(src_url)
                print(f"  📄 원본 제목: {source['title'][:60]}")
                print(f"  🤖 교정 변경 사항 식별 중...")
                changes = ai_sync_with_source(stripped_section, source, instruction)
                print(f"  📋 변경 항목 {len(changes)}개")
                html = apply_changes(html, changes)
                write_html(path, html)
            except FileNotFoundError:
                print(f"  ⚠️  {path} 없음 — 건너뜀")
            except Exception as e:
                print(f"  ❌ {path} 교정 실패: {e}")
                sys.exit(1)

    else:
        msg = result.get("message", "이해할 수 없는 명령이에요.")
        print(f"⚠️  {msg}")
        sys.exit(0)

    print("\n✅ 명령 실행 완료!")


if __name__ == "__main__":
    main()
