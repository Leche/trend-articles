#!/usr/bin/env python3
"""
트렌드림 기사 큐레이션 자동화 스크립트
- 우선 사이트 스캔 → 기사 선정 → 요약 생성 → 썸네일 다운로드 → HTML 생성
- GitHub Actions에서 실행되며, Claude API를 사용합니다.
"""

import os
import re
import sys
import json
import glob
import base64
import datetime
import textwrap
from io import BytesIO
from urllib.parse import urljoin, urlparse

import anthropic
import requests
from bs4 import BeautifulSoup

# ─── 설정 ────────────────────────────────────────────────────
ARTICLE_COUNT = int(os.environ.get("ARTICLE_COUNT", "6"))
CUSTOM_DATE = os.environ.get("CUSTOM_DATE", "").strip()
KST = datetime.timezone(datetime.timedelta(hours=9))

PRIORITY_SITES = [
    "https://www.surfit.io",
    "https://techcrunch.com/category/apps/",
    "https://designcompass.org/magazine/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

# ─── 날짜 계산 ───────────────────────────────────────────────
if CUSTOM_DATE:
    TODAY = datetime.datetime.strptime(CUSTOM_DATE, "%Y-%m-%d").date()
else:
    TODAY = datetime.datetime.now(KST).date()

WEEKDAY_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
DATE_DISPLAY = f"{TODAY.year}. {TODAY.month}. {TODAY.day} {WEEKDAY_KO[TODAY.weekday()]}"
DATE_PREFIX = TODAY.strftime("%y%m%d")

print(f"📅 큐레이션 날짜: {DATE_DISPLAY}")
print(f"📰 기사 개수: {ARTICLE_COUNT}개")


# ─── 과거 기사 크로스체크 ──────────────────────────────────────
def load_past_articles():
    """기존 HTML 파일들에서 기사 제목과 링크를 추출"""
    past = []
    html_files = glob.glob("*.html") + glob.glob("**/*.html", recursive=True)
    html_files = list(set(html_files))

    for fp in html_files:
        if "guide" in fp.lower():
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            # 제목 추출
            titles = re.findall(r'class="article-title"[^>]*>([^<]+)', content)
            # 링크 추출
            links = re.findall(r'class="article-link"[^>]*href="([^"]+)"', content)
            for t in titles:
                past.append({"title": t.strip(), "file": fp})
            for l in links:
                past.append({"link": l.strip(), "file": fp})
        except Exception:
            continue
    return past


PAST_ARTICLES = load_past_articles()
past_titles = [a["title"] for a in PAST_ARTICLES if "title" in a]
past_links = [a["link"] for a in PAST_ARTICLES if "link" in a]
print(f"🔍 과거 기사 {len(past_titles)}개 제목, {len(past_links)}개 링크 로드 완료")


# ─── 웹 스크래핑 유틸 ─────────────────────────────────────────
def fetch_page(url, timeout=15):
    """URL에서 HTML 가져오기"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  ⚠️  {url} 접근 실패: {e}")
        return None


def extract_og_image(html_text, base_url=""):
    """og:image 메타태그에서 썸네일 URL 추출"""
    soup = BeautifulSoup(html_text, "lxml")
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        img_url = og["content"]
        if img_url.startswith("/"):
            img_url = urljoin(base_url, img_url)
        return img_url
    return None


def download_image_as_base64(img_url, max_size_kb=500):
    """이미지를 다운로드하여 base64로 인코딩"""
    try:
        r = requests.get(img_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "image/jpeg")

        # 확장자 결정
        if "png" in content_type:
            ext = "png"
        elif "gif" in content_type:
            ext = "gif"
        elif "webp" in content_type:
            ext = "webp"
        elif "svg" in content_type:
            ext = "svg+xml"
        else:
            ext = "jpeg"

        img_data = r.content

        # 너무 큰 이미지는 리사이즈
        if len(img_data) > max_size_kb * 1024 and ext in ("jpeg", "png", "webp"):
            try:
                from PIL import Image
                img = Image.open(BytesIO(img_data))
                # 너비 1200px로 리사이즈
                if img.width > 1200:
                    ratio = 1200 / img.width
                    new_size = (1200, int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                buf = BytesIO()
                save_fmt = "JPEG" if ext == "jpeg" else "PNG"
                img.save(buf, format=save_fmt, quality=85, optimize=True)
                img_data = buf.getvalue()
                ext = save_fmt.lower()
            except Exception:
                pass

        b64 = base64.b64encode(img_data).decode("utf-8")
        return f"data:image/{ext};base64,{b64}"
    except Exception as e:
        print(f"  ⚠️  이미지 다운로드 실패: {img_url} → {e}")
        return None


# ─── 우선 사이트 스캔 ─────────────────────────────────────────
def scan_priority_sites():
    """우선 사이트에서 최근 기사 목록 수집"""
    candidates = []
    two_weeks_ago = TODAY - datetime.timedelta(days=14)

    for site_url in PRIORITY_SITES:
        print(f"\n🌐 스캔 중: {site_url}")
        html = fetch_page(site_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")

        # 링크 추출 (각 사이트 구조에 맞게)
        links_found = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("/"):
                href = urljoin(site_url, href)
            # 기사 링크 필터 (날짜 패턴이나 기사 경로 포함)
            parsed = urlparse(href)
            path = parsed.path
            if any(kw in path for kw in ["/202", "/post/", "/article/", "/magazine/"]):
                if href not in links_found:
                    links_found.add(href)
                    title_text = a_tag.get_text(strip=True)[:100] if a_tag.get_text(strip=True) else ""
                    candidates.append({
                        "url": href,
                        "title_hint": title_text,
                        "source": site_url,
                    })

        print(f"  → {len(links_found)}개 후보 발견")

    return candidates


# ─── Claude API로 기사 선정 및 요약 ──────────────────────────
def curate_with_claude(candidates):
    """Claude API를 사용하여 기사 선정, 제목 번역, 요약 생성"""
    client = anthropic.Anthropic()

    # 후보 기사 정보 정리
    candidate_text = ""
    for i, c in enumerate(candidates[:50], 1):  # 최대 50개만 전달
        candidate_text += f"{i}. URL: {c['url']}\n   힌트: {c['title_hint']}\n   출처: {c['source']}\n\n"

    # 과거 기사 목록
    past_text = "과거 큐레이션된 기사 제목:\n"
    for t in past_titles:
        past_text += f"- {t}\n"
    past_text += "\n과거 큐레이션된 기사 링크:\n"
    for l in past_links:
        past_text += f"- {l}\n"

    prompt = f"""당신은 '트렌드림' 뉴스레터의 기사 큐레이터입니다.

## 기사 선정 기준
1. 발행일: 현재 날짜({TODAY.isoformat()}) 기준 2주 이내 기사만
2. 방향성: 빅테크(구글, 애플, 메타, OpenAI 등) 신제품 출시나 새로운 소식 우선
3. 없으면 프로덕트 디자인/UX/그로스 관련 기사
4. 마케팅 기사는 프로덕트 디자인을 통한 그로스 관점만
5. 가끔 사회적 이슈 기사도 포함 가능

## 과거 기사 (중복 방지 - 반드시 크로스체크)
{past_text}

## 후보 기사 목록
{candidate_text}

## 요청
위 후보 중에서, 그리고 필요하다면 후보에 없더라도 직접 떠올린 최근 빅테크/프로덕트 뉴스를 포함하여,
정확히 {ARTICLE_COUNT}개의 기사를 선정해주세요.

**중복 기사는 절대 선정하지 마세요.** 과거 기사 목록에 있는 제목이나 링크와 동일하거나 유사한 기사는 제외합니다.

각 기사에 대해 아래 JSON 형식으로 답변하세요. JSON 배열만 출력하세요:

```json
[
  {{{{
    "url": "기사 원문 URL",
    "title_ko": "한국어 제목 (원문 의미 최대한 살려 번역)",
    "one_line": "20자 내외 한 줄 요약. 명사형 + 마침표로 끝남",
    "summary_1": "첫 번째 요약 (약 100자, 해요체)",
    "summary_2": "두 번째 요약 (약 100자, 해요체)",
    "summary_3": "세 번째 요약 (약 100자, 해요체)"
  }}}}
]
```

## 한 줄 요약 규칙
- 20자 내외, 명사형 + 마침표
- ~해요, ~입니다, ~했다, ~한 것 사용 금지

## 3줄 요약 규칙
- 각 줄 약 100자 내외
- 해요체 (~해요, ~돼요, ~있어요, ~했어요, ~거예요)
- "이 글은", "이 기사는" 등 메타 문장 금지
- 핵심 내용부터 바로 시작
- 현상 / 맥락 / 의미 중심"""

    print("\n🤖 Claude API로 기사 선정 및 요약 중...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    # JSON 추출
    text = response.content[0].text
    json_match = re.search(r'\[[\s\S]*\]', text)
    if not json_match:
        print("❌ Claude 응답에서 JSON을 찾을 수 없습니다.")
        print(text[:500])
        sys.exit(1)

    articles = json.loads(json_match.group())
    print(f"✅ {len(articles)}개 기사 선정 완료")

    return articles


# ─── 각 기사 상세 읽기 + 썸네일 ───────────────────────────────
def enrich_articles(articles):
    """각 기사의 원문을 읽고 내용 보강 + 썸네일 다운로드"""
    enriched = []
    thumb_success = []
    thumb_fail = []

    for i, art in enumerate(articles, 1):
        url = art["url"]
        print(f"\n📖 기사 {i}: {art['title_ko']}")
        print(f"   URL: {url}")

        # 페이지 접근 시도
        html = fetch_page(url)
        thumb_b64 = None

        if html:
            # og:image로 썸네일 시도
            og_img = extract_og_image(html, url)
            if og_img:
                print(f"   🖼️  썸네일 발견: {og_img[:80]}...")
                thumb_b64 = download_image_as_base64(og_img)

        if thumb_b64:
            thumb_success.append(i)
            print(f"   ✅ 썸네일 임베드 성공")
        else:
            thumb_fail.append(i)
            print(f"   ❌ 썸네일 다운로드 실패")

        enriched.append({
            **art,
            "thumbnail_b64": thumb_b64,
            "article_num": i,
        })

    print(f"\n📊 썸네일 결과:")
    print(f"   성공: {thumb_success}")
    print(f"   실패: {thumb_fail}")

    return enriched


# ─── HTML 생성 ────────────────────────────────────────────────
def generate_html(articles):
    """확정된 템플릿으로 HTML 생성"""

    # 기사 카드 HTML 생성
    cards_html = ""
    for art in articles:
        num = f"{art['article_num']:02d}"

        # 썸네일 처리
        if art.get("thumbnail_b64"):
            img_html = f'<div class="image-frame"><img class="article-image" src="{art["thumbnail_b64"]}" alt="썸네일"></div>'
        else:
            img_html = '<div class="image-frame"><div style="width:100%;aspect-ratio:16/10;background:#f5f5f5;display:flex;align-items:center;justify-content:center;color:#999;font-size:14px;">썸네일 없음</div></div>'

        card = f"""<article class="article-item">
<div class="article-label">ARTICLE {num}</div>
<h2 class="article-title">{art['title_ko']}</h2>
<p class="article-summary">{art['one_line']}</p>
{img_html}
<div class="summary-label">SUMMARY</div>
<ul class="bullet-list">
<li class="bullet-item">{art['summary_1']}</li>
<li class="bullet-item">{art['summary_2']}</li>
<li class="bullet-item">{art['summary_3']}</li>
</ul>
<div class="link-label">LINK</div>
<div class="link-box"><a class="article-link" href="{art['url']}" target="_blank">{art['url']}</a></div>
</article>"""
        cards_html += card + "\n"

    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{DATE_DISPLAY} Trend Article Digest</title><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
}}
html,body {{ width:100%; background:#fff; }}
body {{ font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,sans-serif; color:var(--text); }}
.page {{ width:100%; background:#fff; }}
.card {{ width:100%; max-width:100%; background:var(--surface); border-radius:8px; }}
.header {{ padding:28px 20px 24px; border-bottom:1px solid var(--line); }}
.header h1 {{ font-size:clamp(24px,3vw,30px); font-weight:700; line-height:1.2; letter-spacing:-0.02em; }}
.header-meta {{ margin-top:14px; font-size:17px; color:var(--text4); font-weight:600; line-height:1.6; }}
.article-wrap {{ padding:0 20px 24px; }}
.article-item {{ padding:24px 0 28px; border-bottom:1px solid var(--line); }}
.article-item:last-of-type {{ border-bottom:0; }}
.article-label {{ display:inline-block; margin-bottom:14px; padding:7px 10px; background:#fbfbfb; border:1px solid var(--line); border-radius:8px; font-size:10px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase; color:var(--text5); }}
.article-title {{ font-size:clamp(24px,2.7vw,30px); font-weight:700; line-height:1.33; margin-bottom:10px; letter-spacing:-0.02em; word-break:keep-all; }}
.article-summary {{ font-size:clamp(15px,1.8vw,17px); font-weight:500; line-height:1.65; color:var(--text3); margin-bottom:18px; word-break:keep-all; }}
.image-frame {{ margin-bottom:18px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:#fff; }}
.article-image {{ width:100%; height:auto; display:block; background:#fff; border:0; border-radius:8px; object-fit:contain; object-position:center center; }}
.summary-label, .link-label {{ font-size:11px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:var(--text5); margin-bottom:10px; }}
.bullet-list {{ list-style:none; display:grid; gap:10px; margin-bottom:18px; }}
.bullet-item {{ font-size:clamp(14px,1.8vw,16px); line-height:1.72; color:var(--text2); padding-left:16px; position:relative; word-break:keep-all; }}
.bullet-item::before {{ content:'·'; position:absolute; left:0; top:0; color:var(--text4); font-weight:700; }}
.link-box {{ display:block; padding:14px 16px; border:1px solid var(--link-border); border-radius:8px; background:var(--link-bg); }}
.article-link {{ display:block; font-size:14px; line-height:1.75; color:var(--link-text); text-decoration:none; word-break:break-all; }}
.article-link:hover {{ text-decoration:underline; }}
@media (max-width:767px) {{ .article-summary,.bullet-item{{font-size:17px;}} }}
@media (min-width:768px) {{
  html,body{{background:var(--page);}} .page{{background:var(--page);padding:28px;}}
  .card{{max-width:980px;margin:0 auto;border:1px solid var(--line);background:var(--surface);border-radius:8px;}}
  .header{{padding:40px 32px 32px;}} .article-wrap{{padding:0 32px 32px;}} .article-item{{padding:28px 0 32px;}}
}}
@media (min-width:1200px) {{
  .page{{padding:36px;}}
  .card{{max-width:1320px;}}
  .header{{padding:48px 40px 36px;}}
  .article-wrap{{
    padding:0 40px 40px;
    display:grid;
    grid-template-columns:minmax(0,1fr) minmax(0,1fr);
    column-gap: 40px;
  }}
  .article-item{{ padding:28px 0 32px; }}
}}
@media (min-width: 1200px) {{
  .image-frame {{ width: 100%; aspect-ratio: 16 / 10; overflow: hidden; border-radius: 8px; background: #fff; }}
  .image-frame .article-image {{ width: 100%; height: 100%; display: block; object-fit: cover; object-position: center center; }}
}}
@media (max-width: 1199px) {{
  .image-frame {{ aspect-ratio: auto; }}
  .image-frame .article-image {{ width: 100%; height: auto; display: block; object-fit: contain; object-position: center center; }}
}}
@media (min-width: 1200px) {{
  .article-item:nth-last-child(-n+2) {{ border-bottom: none !important; padding-bottom: 0 !important; margin-bottom: 0 !important; }}
}}
.link-box a, .link-url, .article-link, .url-text {{
  display: block !important; width: 100% !important; min-width: 0 !important;
  overflow: hidden !important; white-space: nowrap !important; text-overflow: ellipsis !important;
}}
</style></head><body><div class="page"><div class="card"><header class="header"><h1>{DATE_DISPLAY}</h1><div class="header-meta">Trend Article Digest</div></header><main class="article-wrap article-list">
{cards_html}
</main></div></div></body></html>"""

    return html


# ─── 메인 실행 ────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("🚀 트렌드림 기사 큐레이션 자동화 시작")
    print("=" * 60)

    # 1. 우선 사이트 스캔
    candidates = scan_priority_sites()
    print(f"\n📋 총 {len(candidates)}개 후보 기사 수집")

    # 2. Claude API로 기사 선정 + 요약
    articles = curate_with_claude(candidates)

    # 기사 수 검증
    if len(articles) != ARTICLE_COUNT:
        print(f"⚠️  요청 {ARTICLE_COUNT}개 vs 선정 {len(articles)}개 — 조정 필요")
        articles = articles[:ARTICLE_COUNT]

    # 3. 각 기사 상세 + 썸네일
    enriched = enrich_articles(articles)

    # 4. HTML 생성
    html_content = generate_html(enriched)

    # 5. 파일 저장
    # index.html로 저장 (GitHub Pages 메인)
    output_path = "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\n💾 저장 완료: {output_path}")

    # 날짜별 아카이브도 저장
    archive_path = f"{DATE_PREFIX}_index.html"
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"💾 아카이브 저장: {archive_path}")

    # 썸네일 실패 기사 목록
    failed = [a["article_num"] for a in enriched if not a.get("thumbnail_b64")]
    if failed:
        print(f"\n⚠️  썸네일 미확보 기사: {failed}")
        print("   → 수동으로 이미지를 제공하거나 placeholder가 표시됩니다.")

    print("\n" + "=" * 60)
    print("✅ 큐레이션 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
