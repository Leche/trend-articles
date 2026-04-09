#!/usr/bin/env python3
"""
자연어 명령을 Claude API로 해석하고 트렌드림 HTML을 직접 수정하는 스크립트
- 링크 수정: "5번 기사 링크를 https://... 로 바꿔줘"
- 순서 조정: "3번 기사를 1번으로 이동해줘"
"""

import os
import re
import sys
import json
import datetime
import anthropic

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

3. 트리거 페이지 텍스트 수정 (trigger.html의 제목/서브타이틀 등):
   {"action": "edit_text", "file": "trigger.html", "items": [{"selector": "p.subtitle", "new": "새 텍스트"}]}
   지원 셀렉터: "h1" (메인 타이틀), "p.subtitle" (서브타이틀)

지원하지 않는 액션 (기사 내용 교체 등 복잡한 작업):
   {"action": "unsupported", "message": "간단한 이유"}

이해할 수 없는 요청:
   {"action": "unknown", "message": "이해할 수 없는 이유 간단히"}

JSON만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.""",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        raise ValueError(f"Claude 응답 파싱 실패: {raw}")
    return json.loads(m.group())


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


def edit_text_in_html(html: str, selector: str, new_text: str) -> str:
    """CSS selector 기반 텍스트 교체 (예: 'p.subtitle', 'h1')"""
    if '.' in selector:
        tag, cls = selector.split('.', 1)
        pattern = rf'(<{re.escape(tag)}[^>]*class="[^"]*{re.escape(cls)}[^"]*"[^>]*>)(.*?)(</{re.escape(tag)}>)'
    else:
        pattern = rf'(<{re.escape(selector)}(?:\s[^>]*)?>)(.*?)(</{re.escape(selector)}>)'
    replaced = re.sub(pattern, lambda m: m.group(1) + new_text + m.group(3), html, flags=re.DOTALL)
    if replaced == html:
        raise ValueError(f"'{selector}' 요소를 찾을 수 없어요.")
    return replaced


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

    elif action == "edit_text":
        file_target = result.get("file", "trigger.html")
        items = result.get("items", [])
        for item in items:
            selector = item.get("selector", "")
            new_text = item.get("new", "")
            print(f"\n✏️  텍스트 수정: [{file_target}] '{selector}' → '{new_text}'")
            try:
                html = read_html(file_target)
                html = edit_text_in_html(html, selector, new_text)
                write_html(file_target, html)
            except FileNotFoundError:
                print(f"  ⚠️  {file_target} 없음 — 건너뜀")
            except Exception as e:
                print(f"  ❌ {file_target} 수정 실패: {e}")
                sys.exit(1)

    elif action == "unsupported":
        msg = result.get("message", "지원하지 않는 액션이에요.")
        print(f"⚠️  {msg}")
        sys.exit(0)  # 워크플로우 실패 아님, 경고로만 처리

    else:
        msg = result.get("message", "이해할 수 없는 명령이에요.")
        print(f"❌ {msg}")
        sys.exit(1)

    print("\n✅ 명령 실행 완료!")


if __name__ == "__main__":
    main()
