"""
백필: 과거 다이제스트 HTML들에 AI 생성 인트로 일괄 추가.
- 각 2026-*/index.html에서 article 데이터 추출
- Claude API로 1~2문장 인트로 생성
- HTML <main class="article-wrap..."> 직후에 <section class="digest-intro" data-static-intro> 삽입
- 이미 digest-intro가 있는 파일은 스킵
"""
import os, re, glob, sys
import anthropic


def extract_articles(html):
    """HTML에서 기사 데이터 추출 (title, one_line, bullets)"""
    articles = []
    for m in re.finditer(r'<article class="article-item">(.*?)</article>', html, re.DOTALL):
        inner = m.group(1)
        # 옛 포맷(03-13)에선 <section class="article-item">. 별도 처리.
        title_m = re.search(r'<h2 class="article-title">([^<]+)</h2>', inner)
        oneline_m = re.search(r'<p class="article-summary">([^<]+)</p>', inner)
        bullets = re.findall(r'<li class="bullet-item">([^<]+)</li>', inner)
        articles.append({
            'title': title_m.group(1).strip() if title_m else '',
            'one_line': oneline_m.group(1).strip() if oneline_m else '',
            'bullets': [b.strip() for b in bullets[:3]],
        })
    # 옛 포맷 fallback (section 태그)
    if not articles:
        for m in re.finditer(r'<section class="article-item">(.*?)</section>', html, re.DOTALL):
            inner = m.group(1)
            title_m = re.search(r'<h2 class="article-title">([^<]+)</h2>', inner)
            oneline_m = re.search(r'<p class="article-summary">([^<]+)</p>', inner)
            bullets = re.findall(r'<li class="bullet-item">([^<]+)</li>', inner)
            articles.append({
                'title': title_m.group(1).strip() if title_m else '',
                'one_line': oneline_m.group(1).strip() if oneline_m else '',
                'bullets': [b.strip() for b in bullets[:3]],
            })
    return articles


def calculate_reading_time(articles):
    total = 0
    for a in articles:
        total += len(a.get('title', '')) + len(a.get('one_line', ''))
        total += sum(len(b) for b in a.get('bullets', []))
    return max(1, round(total / 700))


def generate_intro(articles, client):
    article_text = ""
    for i, a in enumerate(articles, 1):
        article_text += f"{i}. [{a['title']}]\n   {a['one_line']}\n\n"
    prompt = f"""당신은 트렌드림이라는 매일 큐레이션되는 아티클 다이제스트의 큐레이터입니다. 아래는 오늘 큐레이션된 기사 목록입니다.

{article_text}이 기사들을 읽기 전, 독자가 오늘의 흐름을 한눈에 파악할 수 있도록 1~2문장의 친근한 인트로를 작성해주세요.

조건:
- 친근하고 자연스러운 한국어 ("~요" 톤)
- 70~120자 내
- 핵심 테마 1~2개를 자연스럽게 언급
- 기사 번호 언급 X
- 광고스럽거나 과장된 표현 X
- 매번 같은 패턴이 아닌 자연스러운 표현 사용

응답: 인트로 텍스트만 (다른 설명, 따옴표 등 없이)"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def insert_intro(html, intro_text, count, mins):
    if 'class="digest-intro"' in html:
        return html, False
    intro_html = (
        f'<section class="digest-intro" data-static-intro>'
        f'<div class="digest-meta"><span>{count}개 기사</span><span>·</span><span>약 {mins}분 읽기</span></div>'
        f'<p class="digest-summary">{intro_text}</p>'
        f'</section>'
    )
    # main 또는 div의 article-wrap 직후 삽입
    new_html, n = re.subn(
        r'(<(?:main|div)\s+class="article-wrap[^"]*"[^>]*>)',
        lambda m: m.group(1) + intro_html,
        html,
        count=1
    )
    return new_html, n > 0


def process_file(path, client):
    with open(path) as f:
        html = f.read()
    if 'class="digest-intro"' in html:
        return False, "already has intro"
    articles = extract_articles(html)
    if not articles:
        return False, "no articles found"
    try:
        intro = generate_intro(articles, client)
    except Exception as e:
        return False, f"intro gen failed: {e}"
    mins = calculate_reading_time(articles)
    new_html, ok = insert_intro(html, intro, len(articles), mins)
    if not ok:
        return False, "insert failed"
    with open(path, 'w') as f:
        f.write(new_html)
    return True, f"ok ({len(articles)}개, {mins}분)"


if __name__ == '__main__':
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("ERROR: ANTHROPIC_API_KEY env var not set")
        sys.exit(1)
    client = anthropic.Anthropic()
    paths = sorted(
        glob.glob('2026-*/index.html')
        + glob.glob('test/index.html')
        + (glob.glob('index.html') if os.path.exists('index.html') else [])
    )
    if len(sys.argv) > 1:
        paths = sys.argv[1:]
    print(f"Processing {len(paths)} files...")
    fail = 0
    for p in paths:
        ok, msg = process_file(p, client)
        status = "OK" if ok else "SKIP"
        print(f"  [{status}] {p}: {msg}")
        if not ok and msg not in ("already has intro",):
            fail += 1
    print(f"Done. Failures: {fail}/{len(paths)}")
