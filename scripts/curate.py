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
ARTICLE_COUNT = int(os.environ.get("ARTICLE_COUNT", "8"))
CUSTOM_DATE = os.environ.get("CUSTOM_DATE", "").strip()
REPLACE_URLS = os.environ.get("REPLACE_URLS", "").strip()
TEST_MODE = os.environ.get("TEST_MODE", "").strip().lower() == "true"
# CURATE_MODE: "legacy" (default, scrape SURFIT_CATEGORIES + PRIORITY_SITES)
#              | "web_search" (internet-wide via Claude web_search tool — billed per use)
CURATE_MODE = os.environ.get("CURATE_MODE", "legacy").strip().lower()
KST = datetime.timezone(datetime.timedelta(hours=9))

SURFIT_CATEGORIES = [
    "https://www.surfit.io/explore/startup/new-product",
    "https://www.surfit.io/explore/startup/ai",
    "https://www.surfit.io/explore/design/ui-ux",
    "https://www.surfit.io/explore/startup/business-trend",
]

PRIORITY_SITES = [
    # 기존 사이트 (surfit.io는 Playwright로 별도 스캔)
    "https://techcrunch.com/category/apps/",
    "https://designcompass.org/magazine/",
    # 디바이스 / 모바일
    "https://www.phonearena.com",
    "https://9to5mac.com/?s=siri",
    "https://9to5google.com",
    "https://www.theverge.com",
    # 빅테크 공식 뉴스룸
    "https://www.apple.com/newsroom/",
    "https://news.samsung.com/kr/",
    "https://openai.com/ko-KR/news/",
    "https://www.anthropic.com/news",
    "https://about.fb.com/news/",
    "https://about.instagram.com/blog/?locale=ko_KR",
    "https://blog.google",
    "https://blog.youtube/news-and-events/",
    "https://www.uber.com/us/en/newsroom/",
    # 국내 테크 / 프로덕트
    "https://fficial.naver.com/contentsAll?categorySeq=1004&pageNumber=1",
    "https://m.blog.naver.com/PostList.naver?blogId=naver_search&tab=1",
    "https://toss.tech",
    "https://about.daangn.com/company/pr/",
    "https://oliveyoung.tech",
    "https://www.woowahan.com/newsroom/report?page=1",
    "https://bcut.baemin.com/category/eat/",
    # 디자인 툴
    "https://www.figma.com/ko-kr/release-notes/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

# 큐레이션에서 제외할 도메인 (서핏 등 리다이렉트 링크는 최종 목적지 기준)
BLOCKED_DOMAINS = ["ditoday.com"]

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


# ─── 교체 URL 파싱 ───────────────────────────────────────────
def parse_replace_urls(replace_str):
    """'1=https://...,3=https://...' 형식 파싱 → {1: 'https://...', 3: 'https://...'}"""
    if not replace_str:
        return {}
    replacements = {}
    for item in replace_str.split(","):
        item = item.strip()
        if "=" in item:
            num, url = item.split("=", 1)
            try:
                replacements[int(num.strip())] = url.strip()
            except ValueError:
                continue
    return replacements


REPLACEMENTS = parse_replace_urls(REPLACE_URLS)
if REPLACEMENTS:
    print(f"🔄 기사 교체 모드: {REPLACEMENTS}")


# ─── 과거 기사 크로스체크 ──────────────────────────────────────
def load_past_articles():
    """기존 HTML 파일들에서 기사 제목과 링크를 추출 (최신 날짜부터)"""
    past = []
    html_files = glob.glob("*.html") + glob.glob("**/*.html", recursive=True)
    # 최신 날짜 폴더(2026-05-03 등)가 먼저 오도록 내림차순 정렬
    html_files = sorted(set(html_files), reverse=True)

    today_folder = TODAY.strftime("%Y-%m-%d")
    for fp in html_files:
        if "guide" in fp.lower():
            continue
        # 루트 파일(index.html 등)·test 폴더는 아카이브가 아니므로 과거 대상에서 제외.
        # 오늘 날짜 폴더도 제외 — 재실행 시 자기 자신을 '과거 중복'으로 보지 않도록.
        if "/" not in fp or fp.startswith("test/") or fp.startswith(today_folder + "/"):
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


# ─── Playwright 유틸 ──────────────────────────────────────────
def _pw_available():
    """Playwright 사용 가능 여부 확인"""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_page_playwright(url, timeout=30000):
    """Playwright 헤드리스 브라우저로 페이지 접근 (JS 렌더링 지원)"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"
            )
            # 봇 감지 우회: webdriver 프로퍼티 제거
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, wait_until="networkidle", timeout=timeout)
            # SPA 렌더링 대기: body 내 텍스트가 충분히 로드될 때까지 추가 대기
            try:
                page.wait_for_function(
                    "document.body && document.body.innerText.length > 500",
                    timeout=10000
                )
            except Exception:
                pass  # 타임아웃이어도 현재 상태로 진행
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  ⚠️  Playwright 접근 실패: {e}")
        return None


# ─── 웹 스크래핑 유틸 ─────────────────────────────────────────
def _has_real_content(html_text, min_text_len=200):
    """HTML에서 실제 텍스트 콘텐츠가 충분한지 확인 (JS 렌더링 필요 여부 판단)"""
    try:
        soup = BeautifulSoup(html_text, "lxml")
        for tag in soup.find_all(["script", "style", "noscript", "meta", "link"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return len(text) >= min_text_len
    except Exception:
        return False


def _fetch_google_cache(url, timeout=15):
    """Google 캐시에서 페이지 가져오기 (직접 접근 불가 사이트 fallback)"""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
    try:
        r = requests.get(cache_url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and _has_real_content(r.text):
            print(f"  ✅ Google 캐시에서 콘텐츠 확보 성공")
            return r.text
    except Exception as e:
        print(f"  ⚠️  Google 캐시 접근 실패: {e}")
    return None


def fetch_page(url, timeout=15):
    """URL에서 HTML 가져오기 (실제 콘텐츠 부족 시 Playwright → Google 캐시 폴백)"""
    html = None
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        html = r.text
        if _has_real_content(html):
            return html
        print(f"  ⚠️  {url} HTML은 받았으나 텍스트 콘텐츠 부족, Playwright로 재시도")
    except Exception as e:
        print(f"  ⚠️  {url} requests 접근 실패: {e}")

    # Playwright 폴백
    if _pw_available():
        print(f"  🔄 Playwright로 재시도: {url}")
        pw_html = fetch_page_playwright(url)
        if pw_html and _has_real_content(pw_html):
            return pw_html

    # Google 캐시 폴백
    print(f"  🔄 Google 캐시로 재시도: {url}")
    cache_html = _fetch_google_cache(url, timeout)
    if cache_html:
        return cache_html

    # 모두 실패 시 원본이라도 반환
    if _pw_available():
        pw_html = fetch_page_playwright(url)
        return pw_html or html
    else:
        print(f"  ❌ Playwright 미설치, 페이지 접근 불가: {url}")
        return html


def extract_og_image(html_text, base_url=""):
    """썸네일 이미지 URL 추출. og:image → twitter:image → link[image_src] 순으로 시도.
    designcompass 등 og:image 의 property/name 표기가 제각각인 사이트 대응."""
    soup = BeautifulSoup(html_text, "lxml")
    candidates = []
    for attrs in (
        {"property": "og:image"},
        {"property": "og:image:secure_url"},
        {"name": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
        {"name": "twitter:image:src"},
    ):
        for tag in soup.find_all("meta", attrs=attrs):
            content = tag.get("content")
            if content and content.strip():
                candidates.append(content.strip())
    link = soup.find("link", rel="image_src")
    if link and link.get("href"):
        candidates.append(link["href"].strip())

    for img_url in candidates:
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            img_url = urljoin(base_url, img_url)
        if img_url.startswith("http"):
            return img_url
    return None


def download_image_as_base64(img_url, max_size_kb=500, referer=None):
    """이미지를 다운로드하여 base64로 인코딩.
    referer: hotlink 차단(designcompass 등) 우회용 — 기사 페이지 URL을 넘기면
    이미지 CDN이 정상 요청으로 인식할 확률이 높아짐."""
    try:
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        r = requests.get(img_url, headers=headers, timeout=15)
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


# ─── 서핏 Playwright 스캔 ────────────────────────────────────
def scan_surfit_categories():
    """Playwright로 서핏 카테고리 페이지에서 기사 수집 (JS 렌더링 필요)"""
    import re as _re
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️  playwright 미설치 — 서핏 스킵")
        return []

    MAX_PER_CAT = 5
    candidates = []
    print("\n🎭 Playwright로 서핏 스캔 시작...")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=HEADERS["User-Agent"])
            page = context.new_page()

            for cat_url in SURFIT_CATEGORIES:
                print(f"\n🌐 서핏 스캔 중: {cat_url}")
                try:
                    page.goto(cat_url, wait_until="networkidle", timeout=30000)
                    html = page.content()
                    soup = BeautifulSoup(html, "lxml")

                    site_candidates = []
                    seen_urls = set()

                    for article in soup.find_all("article"):
                        # surfit.io/link/XXXXX 형태 링크 추출
                        link_tag = article.find(
                            "a", href=lambda h: h and "surfit.io/link/" in h
                        )
                        if not link_tag:
                            continue
                        url = link_tag["href"]
                        if not url.startswith("http"):
                            url = "https://surfit.io" + url
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        # 제목 추출
                        heading = article.find(["h1", "h2", "h3", "h4"])
                        title_hint = heading.get_text(strip=True)[:100] if heading else ""

                        # 날짜 추출 (YYYY.MM.DD 패턴)
                        date_hint = ""
                        for text_node in article.find_all(string=_re.compile(r"\d{4}\.\d{2}\.\d{2}")):
                            m = _re.search(r"(\d{4})\.(\d{2})\.(\d{2})", text_node)
                            if m:
                                date_hint = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                                break

                        site_candidates.append({
                            "url": url,
                            "title_hint": title_hint,
                            "source": "https://www.surfit.io",
                            "date_hint": date_hint,
                        })

                    candidates.extend(site_candidates[:MAX_PER_CAT])
                    print(f"  → {len(site_candidates)}개 발견, {min(len(site_candidates), MAX_PER_CAT)}개 선택")

                except Exception as e:
                    print(f"  ❌ {cat_url} 스캔 실패: {e}")

            browser.close()

    except Exception as e:
        print(f"  ❌ Playwright 실행 실패: {e}")

    return candidates


# ─── 우선 사이트 스캔 ─────────────────────────────────────────
def scan_priority_sites():
    """우선 사이트에서 최근 기사 목록 수집"""
    # ── 서핏은 Playwright로 별도 스캔 ──
    candidates = scan_surfit_categories()

    two_weeks_ago = TODAY - datetime.timedelta(days=14)

    MAX_PER_SITE = 5  # 사이트당 최대 후보 수 (모든 사이트가 골고루 반영되도록)

    for site_url in PRIORITY_SITES:
        print(f"\n🌐 스캔 중: {site_url}")
        html = fetch_page(site_url)
        if not html:
            print(f"  ❌ 접근 실패 — 건너뜀")
            continue

        soup = BeautifulSoup(html, "lxml")

        # 링크 추출 (각 사이트 구조에 맞게)
        links_found = set()
        site_candidates = []
        article_patterns = [
            "/202", "/post/", "/article/", "/magazine/",
            "/news/", "/newsroom/", "/blog/", "/press/",
            "/release-notes/", "/tech/", "/pr/", "/story/",
            "/archives/", "/entry/", "/contents/",
        ]
        # 제외 패턴 (카테고리/태그 페이지 등)
        skip_patterns = [
            "/category/", "/tag/", "/page/", "/author/",
            "/search?", "/login", "/signup", "#comment",
        ]
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("/"):
                href = urljoin(site_url, href)
            parsed = urlparse(href)
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            # 같은 도메인 또는 알려진 도메인의 기사만
            if not href.startswith("http"):
                continue
            if any(skip in path.lower() for skip in skip_patterns):
                continue
            if any(kw in path for kw in article_patterns) or len(path.strip("/").split("/")) >= 2:
                if href not in links_found and href != site_url:
                    links_found.add(href)
                    title_text = a_tag.get_text(strip=True)[:100] if a_tag.get_text(strip=True) else ""
                    site_candidates.append({
                        "url": href,
                        "title_hint": title_text,
                        "source": site_url,
                    })

        # 사이트당 최대 MAX_PER_SITE개만 추가 (상위 링크 우선)
        candidates.extend(site_candidates[:MAX_PER_SITE])
        print(f"  → {len(links_found)}개 발견, {min(len(site_candidates), MAX_PER_SITE)}개 선택")

    # 후보 URL 중복 제거 (여러 카테고리에 같은 기사가 잡히는 경우 방지)
    seen_cand = set()
    unique = []
    for c in candidates:
        key = _normalize_url(c["url"])
        if key and key in seen_cand:
            continue
        if key:
            seen_cand.add(key)
        unique.append(c)
    dropped = len(candidates) - len(unique)
    if dropped:
        print(f"\n🧹 후보 중복 URL {dropped}건 제거")
    candidates = unique

    # 출처 분포 리포트
    source_counts = {}
    for c in candidates:
        domain = urlparse(c["source"]).netloc
        source_counts[domain] = source_counts.get(domain, 0) + 1
    print(f"\n📊 출처 분포: {source_counts}")
    print(f"📋 총 {len(candidates)}개 후보 (사이트 {len(source_counts)}곳)")

    return candidates


# ─── Claude API로 기사 선정 및 요약 ──────────────────────────
def curate_with_claude(candidates):
    """Claude API를 사용하여 기사 선정, 제목 번역, 요약 생성"""
    client = anthropic.Anthropic(max_retries=8)

    # 중복·차단 도메인으로 빠지는 분을 감안해 여유있게 선정 요청 → 후처리 후 ARTICLE_COUNT개로 맞춤
    select_count = ARTICLE_COUNT + 4

    # 후보 기사 정보 정리 (최대 100개, 다양한 출처 유지)
    candidate_text = ""
    for i, c in enumerate(candidates[:100], 1):
        candidate_text += f"{i}. URL: {c['url']}\n   힌트: {c['title_hint']}\n   출처: {c['source']}\n"
        if c.get("date_hint"):
            candidate_text += f"   날짜: {c['date_hint']}\n"
        candidate_text += "\n"

    # 과거 기사 목록
    past_text = "과거 큐레이션된 기사 제목:\n"
    for t in past_titles:
        past_text += f"- {t}\n"
    past_text += "\n과거 큐레이션된 기사 링크:\n"
    for l in past_links:
        past_text += f"- {l}\n"

    prompt = f"""당신은 '트렌드림' 뉴스레터의 기사 큐레이터입니다.
트렌드림은 프로덕트, 디자인, 테크, 비즈니스에 관심 있는 독자들을 위한 뉴스레터입니다.

## 기사 선정 기준
1. 발행일: 현재 날짜({TODAY.isoformat()}) 기준 2주 이내 기사만
2. 구성 가이드 (전체 {select_count}개 기준):
   - 빅테크(구글, 애플, 메타, OpenAI 등) 신제품/업데이트 소식: 1~2개
   - 나머지는 아래 범주에서 자유롭게 조합:
     • 프로덕트 디자인 / UX / UI 트렌드
     • 프로덕트 그로스 / 비즈니스 인사이트
     • AI 서비스/툴 활용 및 트렌드
     • 국내외 스타트업/서비스 새로운 시도
     • 사회적으로 주목할 만한 테크/비즈니스 이슈
3. 마케팅 기사는 프로덕트 그로스 관점인 것만 허용
4. 후보 목록에 없더라도 당신이 알고 있는 최근 기사 중 트렌드림 독자에게 가치 있다고 판단되면 자유롭게 추가 가능
5. 다양한 관점과 주제가 섞인 구성을 지향 — 비슷한 주제끼리 몰리지 않도록

## 과거 기사 (중복 방지 - 반드시 크로스체크)
{past_text}

## 후보 기사 목록
{candidate_text}

## 요청
위 후보 중에서, 그리고 필요하다면 후보에 없더라도 직접 떠올린 최근 빅테크/프로덕트 뉴스를 포함하여,
서로 다른 실제 기사 {select_count}개를 선정해주세요. (후처리 중복 제거 후 최종 {ARTICLE_COUNT}개로 추려집니다)

**절대 규칙**: 모든 항목은 실제로 존재하는 개별 기사여야 합니다.
- 중복이거나 적합한 기사를 못 찾으면 그 자리에 **다른 기사**를 고르세요.
- '중복', '재선정 제외', 'placeholder' 등의 표시를 제목·요약에 넣은 가짜 항목을 절대 만들지 마세요.
- {select_count}개를 채우지 못하겠으면 가짜로 채우지 말고 차라리 더 적은 개수로 응답하세요.

**출처 다양성 필수**: 같은 출처(사이트)에서 최대 2개까지만 선정하세요. 가능한 한 서로 다른 사이트에서 기사를 골라야 합니다.
**중복 기사는 절대 선정하지 마세요.** 과거 기사 목록에 있는 제목이나 링크와 동일하거나 유사한 기사는 제외합니다.

각 기사에 대해 아래 JSON 형식으로 답변하세요. JSON 배열만 출력하세요:

```json
[
  {{
    "url": "기사 원문 URL",
    "title_ko": "한국어 제목 (원문 의미 최대한 살려 번역)",
    "one_line": "20자 내외 한 줄 요약. 명사형 + 마침표로 끝남",
    "summary_1": "첫 번째 요약 (약 100자, 해요체)",
    "summary_2": "두 번째 요약 (약 100자, 해요체)",
    "summary_3": "세 번째 요약 (약 100자, 해요체)"
  }}
]
```

## JSON 출력 주의 (필수)
- 유효한 JSON만 출력. 문자열 값 안의 큰따옴표(")는 반드시 \\" 로 이스케이프.
- 문자열 안에 줄바꿈·제어문자 금지. 배열 마지막 요소 뒤 trailing comma 금지.

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

    # 최대 3회 시도 — LLM이 깨진 JSON을 반환하면 재생성
    articles = None
    for attempt in range(3):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # 코드펜스(```json … ```) 우선, 없으면 최외곽 대괄호 매칭
        fence_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', text)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            bracket_match = re.search(r'\[[\s\S]*\]', text)
            json_str = bracket_match.group(0) if bracket_match else None

        if not json_str:
            print(f"  ⚠️  JSON 블록을 찾을 수 없음 (시도 {attempt + 1}/3)")
            continue

        try:
            articles = json.loads(json_str)
            break
        except json.JSONDecodeError as e:
            print(f"  ⚠️  JSON 파싱 실패 (시도 {attempt + 1}/3): {e}")
            # 흔한 LLM 오류 보정: 제어문자 제거 + trailing comma 제거
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
            cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
            try:
                articles = json.loads(cleaned)
                print(f"  ✅ 보정 후 파싱 성공")
                break
            except json.JSONDecodeError:
                continue

    if articles is None:
        print("❌ 3회 시도 후에도 Claude 응답 JSON 파싱 실패")
        sys.exit(1)

    print(f"✅ {len(articles)}개 기사 1차 선정")

    # 후처리: 같은 큐레이션 내 + 과거 중복 제거 (legacy 모드도 안전망 적용)
    articles = dedup_articles(articles)
    print(f"✅ 중복 제거 후 {len(articles)}개")

    return articles


# ─── Claude web_search로 인터넷 전체 큐레이션 ──────────────────
def _normalize_url(u):
    """URL 정규화: 비교용. 프로토콜·쿼리·프래그먼트 무시, 트레일링 슬래시 제거."""
    if not u:
        return ""
    u = u.strip().lower()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = re.split(r'[?#]', u, 1)[0]
    return u.rstrip('/')


def resolve_final_url(url, timeout=8):
    """리다이렉트(서핏 link 등)를 따라가 최종 URL 반환. 실패 시 원본 반환."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.url:
            return r.url
        # 일부 서버는 HEAD 미지원 → GET 으로 재시도
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, stream=True)
        return r.url or url
    except Exception:
        return url


def _is_placeholder_article(art):
    """LLM이 기사를 채우지 못해 넣은 메타/placeholder 항목인지 판별.
    (예: 제목에 '(재선정 제외 — 중복)', 요약에 '중복 기사 제외.' 같은 표현)"""
    text = ((art.get("title_ko") or "") + " " + (art.get("one_line") or "")).lower()
    markers = ["재선정 제외", "중복으로 제외", "중복 기사 제외",
               "(중복)", "— 중복", "duplicate", "placeholder"]
    return any(m in text for m in markers)


def dedup_articles(articles):
    """placeholder/메타 항목 + 같은 큐레이션 내 중복(self) + 과거 큐레이션
    중복을 모두 제거. URL(정규화)·제목(소문자) 양쪽 기준."""
    past_link_set = {_normalize_url(l) for l in past_links if l}
    past_title_set = {(t or "").strip().lower() for t in past_titles}

    seen_urls = set()
    seen_titles = set()
    result = []
    for art in articles:
        url_norm = _normalize_url(art.get("url", ""))
        title_norm = (art.get("title_ko") or "").strip().lower()
        label = art.get("title_ko") or art.get("url") or "(제목 없음)"

        if _is_placeholder_article(art):
            print(f"  ⛔ placeholder/메타 항목 제거: {label}")
            continue
        if url_norm and url_norm in seen_urls:
            print(f"  ⛔ 동일 큐레이션 내 중복 URL 제거: {label}")
            continue
        if title_norm and title_norm in seen_titles:
            print(f"  ⛔ 동일 큐레이션 내 중복 제목 제거: {label}")
            continue
        if url_norm and url_norm in past_link_set:
            print(f"  ⛔ 과거 큐레이션 중복 URL 제거: {label}")
            continue
        if title_norm and title_norm in past_title_set:
            print(f"  ⛔ 과거 큐레이션 중복 제목 제거: {label}")
            continue

        if url_norm:
            seen_urls.add(url_norm)
        if title_norm:
            seen_titles.add(title_norm)
        result.append(art)

    removed = len(articles) - len(result)
    if removed:
        print(f"  → 중복 {removed}건 제거, 최종 {len(result)}개")
    return result


def curate_via_web_search():
    """Claude의 web_search 툴로 인터넷 전체에서 기사 큐레이션.
    사이트 화이트리스트 없이, 카테고리 가이드와 한국 사이트 균형 요건만 프롬프트로 통제."""
    client = anthropic.Anthropic(max_retries=8)

    # ── 발행일 범위: 오늘로부터 14일 전 ~ 오늘 ──
    two_weeks_ago = TODAY - datetime.timedelta(days=14)
    date_range_str = f"{two_weeks_ago.isoformat()} ~ {TODAY.isoformat()}"

    # ── 과거 기사: 프롬프트에는 최근 30개만 힌트로, 전체는 Python 후처리에서 사용 ──
    past_text = "## 최근 큐레이션된 기사 (참고용 힌트 — 같은 기사·같은 사건의 다른 매체 보도 금지)\n"
    past_text += "Python 후처리에서 전체 과거 URL과 제목으로 한 번 더 자동 필터링됩니다. 여기서는 의미적 유사성·최근 트렌드 파악용으로만 활용하세요.\n\n"
    past_text += "최근 제목 (newest first):\n"
    for t in past_titles[:30]:
        past_text += f"- {t}\n"
    past_text += "\n최근 링크 (newest first):\n"
    for l in past_links[:30]:
        past_text += f"- {l}\n"

    prompt = f"""당신은 **3년 넘게 '트렌드림'을 운영해온 프로덕트 디자이너 본인**입니다.
트렌드림은 일반 테크 뉴스 게시판이 아니라, 다음 두 가지 축으로 차별화됩니다.

1. **서비스·제품과 관련된 모든 소식을 빠짐없이 챙긴다** — 출시·업데이트·정책 변경·디자인 리뉴얼 등 표면적 뉴스도 포함. 최신 제품 소식을 빠르게 전달하는 것 자체가 목적의 절반.
2. **그 안에서 '프로덕트 디자이너의 시선'이 드러나는 글을 함께 큐레이션한다** — 일반 뉴스 게시판과 차별점. 디자이너·메이커가 직접 쓴 글, 디자인 의사결정·UX 디테일이 보이는 분석, 디자인 시스템·도구·조직 글에 가산점.

## 임무
오늘은 {TODAY.isoformat()} ({WEEKDAY_KO[TODAY.weekday()]})입니다.
**발행일이 {date_range_str} 범위 안에 있는 기사만** 선정 대상입니다 (큐레이션 날짜 기준 14일 이내).
이 범위 밖에 발행된 기사는 어떤 이유로도 선정하지 마세요. 트렌딩이거나 유명해도 14일 초과면 즉시 탈락.
**web_search 툴을 적극 활용**하여 인터넷에서 최신 글을 직접 검색·읽고 적합한 기사를 정확히 {ARTICLE_COUNT}개 골라주세요.

## 발행일 검증 (필수)
- 검색 결과에서 각 후보의 **발행일을 반드시 확인**할 것 (페이지의 published date / `<time>` 태그 / og:article:published_time / 본문 첫줄 날짜 등)
- 발행일이 명시되어 있지 않거나 확인 불가하면 그 기사는 선정 후보에서 제외
- {date_range_str} 범위를 벗어나는 기사는 절대 선정 금지

## 중복 방지 (필수)
- 아래 "과거 큐레이션 링크" 섹션에 있는 URL과 **동일하거나 같은 기사를 가리키는** URL은 절대 선정 금지
- "과거 큐레이션 제목"과 동일하거나 거의 같은 의미의 제목도 금지 (다른 매체의 같은 사건 보도 포함)
- 같은 사건이라도 제목·관점이 명확히 다르고 새로운 정보가 추가된 경우만 예외적으로 허용

## 카테고리 가이드 ({ARTICLE_COUNT}개 구성 — 두 축 균형)

**A. 제품·서비스 트렌드 (≈ 절반)** — 단순 출시·발표 보도도 환영
  • 빅테크(구글/애플/메타/OpenAI/Anthropic/Microsoft 등) 신제품·업데이트
  • 국내외 스타트업·서비스의 새로운 시도, 신규 출시, 정책 변경
  • AI 서비스/툴 신기능
  • 디자인·프로덕트 관점에서 영향이 있는 정책·제도 변화

**B. 프로덕트 디자이너 시선의 글 (≈ 절반, 차별점)**
  • 프로덕트 디자이너·메이커가 **직접 쓴 글** (회고, 인사이트, 케이스 스터디)
  • UX/UI 디테일·디자인 의사결정 과정이 잘 드러나는 분석
  • 디자인 시스템 / 디자인 도구(Figma 등) / 디자인 토큰 / 프로세스 변화
  • 디자인 조직·커리어·팀 구성·디자이너 인터뷰
  • 프로덕트 그로스 인사이트 (디자인이 그로스에 어떻게 기여했는지 류)

## 디자이너 시선 가산점
같은 주제·시점이라면 다음에 해당하는 글을 우선:
- 디자이너·메이커의 1인칭 글 (X사 디자이너의 회고 vs X사가 Y를 출시했다 → 전자 우선)
- 단순 사실 나열보다 "**왜·어떻게·임팩트**"를 짚는 글
- 한국 디자이너 커뮤니티 출처 (brunch story, 폴인, 퍼블리, 토스 디자인 챕터, 당근 디자인, 카카오/네이버 디자인 블로그, 우아한형제들·올리브영·SK·라인 디자인, 디자인컴파스)

## 피해야 할 콘텐츠
- 임원 인사·기업 가십 (제품·디자인과 무관한 것)
- SEO 광고성 마케팅 글 (제품 본질 없이 키워드만 나열)
- 정치·사회 이슈 (테크·프로덕트와 무관한 것)
- 디자인·UX 함의 없는 순수 스펙 비교

## 제외 도메인 (절대 선정 금지)
- ditoday.com — 이 도메인의 기사는 어떤 경우에도 선정하지 마세요.

## 출처 다양성 (필수)
- **한국어 출처 비중 ≥ 40%** — 영어권 편향 방지
  - 한국 기업 블로그/뉴스룸: toss.tech, daangn.com, navercorp, kakao, line, coupang, woowahan.com, oliveyoung.tech, sk*, kt, samsung
  - 한국 IT 언론: IT조선, 디지털타임스, ZDNet Korea, 더기어, BLOTER, 아웃스탠딩, 모비인사이드, 더밀크
  - 한국 디자인·리서치 매체: designcompass, brunch story, 퍼블리, 폴인
- 같은 도메인 최대 2개
- 영문 출처도 함께 (TechCrunch, The Verge, 9to5mac/google, Anthropic/OpenAI/Google blog 등)

## 검색 전략 (디자이너 키워드 적극 활용)
- **디자이너 한국어**: "프로덕트 디자이너 회고", "토스 디자인 시스템", "당근 디자이너 인터뷰", "디자인 의사결정", "디자인 토큰", "디자이너 커리어", "UX 라이팅"
- **디자이너 영어**: "product designer essay", "design case study", "figma update rationale", "design system at \\\\[company\\\\]", "ux writing"
- **일반 한국어**: "토스 신기능", "네이버 AI 출시", "카카오 새 서비스", "당근마켓 업데이트", "쿠팡 발표"
- **일반 영어**: "OpenAI launch this week", "Figma update {TODAY.year}"
- 카테고리별 1~2회 검색하여 후보 풀을 만든 뒤 최종 {ARTICLE_COUNT}개 선정

## 다양성
- 비슷한 주제·출처에 몰리지 않게
- 두 축(A·B) 균형, 한국·해외 균형, 카테고리 분산

{past_text}

## 출력 형식 (엄격)
- 아래 JSON 배열 **하나만** 출력. 그 외에는 단 한 글자도 출력 금지.
- **JSON 안에 주석(`//`, `#`) 절대 금지**. JSON 표준에 주석은 없습니다.
- 추론·고민·후보 비교는 **머릿속으로만** 하고 최종 결과만 JSON으로 출력.
- 마크다운 코드펜스(\\`\\`\\`)는 사용해도 되고 안 해도 됨. 단 JSON은 반드시 valid해야 함.

```json
[
  {{
    "url": "기사 원문 URL (실제 접근 가능한 URL)",
    "title_ko": "한국어 제목 (원문 의미 최대한 살려 번역)",
    "one_line": "20자 내외 한 줄 요약. 명사형 + 마침표로 끝남",
    "summary_1": "첫 번째 요약 (약 100자, 해요체)",
    "summary_2": "두 번째 요약 (약 100자, 해요체)",
    "summary_3": "세 번째 요약 (약 100자, 해요체)"
  }}
]
```

## 한 줄 요약 규칙
- 20자 내외, 명사형 + 마침표
- ~해요/~입니다/~했다/~한 것 사용 금지

## 3줄 요약 규칙 (디자이너 시선이 묻어나도록)
- 각 줄 약 100자 내외, 해요체 (~해요/~돼요/~있어요/~했어요/~거예요)
- "이 글은", "이 기사는" 등 메타 문장 금지
- 핵심부터 바로 시작 — 현상 / 사용자·디자인 임팩트 / 의미·맥락 흐름
- 단순 발표 뉴스라도 **"디자인·UX적으로 무엇이 바뀌는가"** 한 줄은 들어가게
"""

    print(f"\n🌐 Claude web_search로 인터넷 전체에서 큐레이션 (모델: claude-sonnet-4-6)…")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=24000,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 10,
        }],
        messages=[{"role": "user", "content": prompt}],
    )

    print(f"  stop_reason: {response.stop_reason}")
    # tool_use 블록 개수 디버그용
    tool_uses = sum(1 for b in response.content if getattr(b, "type", None) == "server_tool_use")
    if tool_uses:
        print(f"  web_search 호출 횟수: {tool_uses}")

    # 최종 어시스턴트 텍스트 블록만 합치기
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += getattr(block, "text", "")

    # JSON 추출: 1) ```json …``` 코드펜스 우선, 2) 폴백 [ … ] 배열 매칭
    json_str = None
    fence_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', text)
    if fence_match:
        json_str = fence_match.group(1)
    else:
        bracket_match = re.search(r'\[[\s\S]*\]', text)
        if bracket_match:
            json_str = bracket_match.group(0)

    if not json_str:
        print("❌ Claude 응답에서 JSON을 찾을 수 없습니다.")
        print(f"--- stop_reason={response.stop_reason} ---")
        print(f"--- text 전체 ({len(text)} chars) ---")
        print(text or "(빈 텍스트)")
        sys.exit(1)

    try:
        articles = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 실패: {e}")
        print(f"--- 추출된 JSON 문자열 ({len(json_str)} chars) ---")
        print(json_str[:5000])
        sys.exit(1)

    # ── 후처리: 같은 큐레이션 내 + 과거 중복 제거 (안전망) ──
    deduped = dedup_articles(articles)

    if len(deduped) < ARTICLE_COUNT:
        print(f"⚠️  중복 제거 후 {len(deduped)}개만 남음 (요청 {ARTICLE_COUNT}). 프롬프트 강화 필요할 수 있음.")

    print(f"✅ {len(deduped)}개 기사 선정 완료")
    return deduped


# ─── 각 기사 상세 읽기 + 썸네일 ───────────────────────────────
def enrich_articles(articles, target_count=None):
    """각 기사의 원문을 읽고 내용 보강 + 썸네일 다운로드.
    target_count 지정 시 차단 도메인을 건너뛰며 그 개수만큼 채워지면 멈춤
    (앞 단계에서 여유분을 받아두면 차단·중복 제거 후에도 정확히 채울 수 있음)."""
    enriched = []
    thumb_success = []
    thumb_fail = []

    for art in articles:
        if target_count is not None and len(enriched) >= target_count:
            break
        url = art["url"]
        # 서핏 등 리다이렉트 링크는 실제 기사 URL로 해석 — 차단 판정·썸네일 referer에 사용.
        # (referer가 서핏 URL이면 designcompass 등의 hotlink 차단에 걸려 썸네일 실패)
        final_url = resolve_final_url(url) if "surfit.io/link/" in url else url
        final_netloc = urlparse(final_url).netloc.lower()
        if any(b in final_netloc for b in BLOCKED_DOMAINS):
            print(f"\n⛔ 차단 도메인 기사 제외: {final_url}")
            continue

        num = len(enriched) + 1
        print(f"\n📖 기사 {num}: {art['title_ko']}")
        print(f"   URL: {url}")

        # 페이지 접근 시도
        html = fetch_page(url)
        thumb_b64 = None

        if html:
            # og:image 추출·다운로드는 실제 기사 URL(final_url) 기준
            og_img = extract_og_image(html, final_url)
            if og_img:
                print(f"   🖼️  썸네일 발견: {og_img[:80]}...")
                thumb_b64 = download_image_as_base64(og_img, referer=final_url)

        if thumb_b64:
            thumb_success.append(num)
            print(f"   ✅ 썸네일 임베드 성공")
        else:
            thumb_fail.append(num)
            print(f"   ❌ 썸네일 다운로드 실패")

        enriched.append({
            **art,
            "thumbnail_b64": thumb_b64,
            "article_num": num,
        })

    print(f"\n📊 썸네일 결과:")
    print(f"   성공: {thumb_success}")
    print(f"   실패: {thumb_fail}")

    return enriched


# ─── HTML 생성 ────────────────────────────────────────────────
def calculate_reading_time(articles):
    """전체 기사 텍스트 기반 읽기 시간 추정 (한국어 ~700자/분)"""
    total = 0
    for art in articles:
        for k in ('title_ko', 'one_line', 'summary_1', 'summary_2', 'summary_3'):
            total += len(art.get(k, '') or '')
    return max(1, round(total / 700))


def generate_intro(articles):
    """오늘 기사들을 보고 1~2문장 인트로 생성 (Claude)"""
    client = anthropic.Anthropic(max_retries=8)
    article_text = ""
    for i, art in enumerate(articles, 1):
        article_text += f"{i}. [{art.get('title_ko','')}]\n"
        article_text += f"   한 줄: {art.get('one_line','')}\n"
        for k in ('summary_1', 'summary_2', 'summary_3'):
            if art.get(k):
                article_text += f"   - {art[k]}\n"
        article_text += "\n"
    prompt = f"""당신은 트렌드림이라는 매일 큐레이션되는 아티클 다이제스트의 큐레이터입니다. 아래는 오늘 큐레이션된 기사 목록과 각 기사의 요약입니다.

{article_text}독자가 오늘의 큰 흐름을 한눈에 잡을 수 있도록 1~2문장의 인트로를 써주세요.
단순히 기사 제목을 나열하지 말고, 오늘 기사들을 관통하는 **공통된 흐름이나 관점**을 한 문장으로 짚어주세요.

권장 구조 (참고용, 그대로 따르지 말고 자연스럽게 변형):
"[구체 사례 A]부터 [사례 B], [사례 C]까지 — 오늘은 [관통하는 큰 테마/관점]을 보여주는 기사들을 모았어요."

좋은 예시:
"앤트로픽의 인프라 확장부터 AI 에이전트 사고, 이커머스의 MCP 경쟁까지 — 오늘은 AI가 산업 전반을 어떻게 재편하고 있는지 한눈에 볼 수 있는 기사들을 모았어요."

피해야 할 패턴:
- 기사 제목 그대로 나열 후 "...등 N개의 이야기를 담았어요"로 마무리 (큐레이터의 관점 없이 단순 목록)
- "오늘 트렌드림이 큐레이션한 N개의 기사예요" 같은 제네릭 표현
- 기사 번호 언급
- 광고/과장 표현

조건:
- 친근한 "~요" 톤
- 100~140자
- 구체 사례 2~3개를 짧게 인용하되, **반드시 큰 흐름/관점으로 묶어 마무리**
- 매번 같은 표현 패턴 반복 금지

응답: 인트로 텍스트만 (다른 설명, 따옴표 등 없이)"""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[WARN] intro generation failed: {e}")
        return f"오늘 트렌드림이 큐레이션한 {len(articles)}개의 기사를 모았어요."


def generate_html(articles):
    """확정된 템플릿으로 HTML 생성"""

    # AI 인트로 + 읽기 시간
    intro_text = generate_intro(articles)
    reading_mins = calculate_reading_time(articles)
    intro_html = (
        f'<section class="digest-intro" data-static-intro>'
        f'<div class="digest-meta"><span>{len(articles)}개 기사</span><span>·</span><span>약 {reading_mins}분 읽기</span></div>'
        f'<p class="digest-summary">{intro_text}</p>'
        f'</section>'
    )

    # 기사 카드 HTML 생성
    cards_html = ""
    for art in articles:
        num = f"{art['article_num']:02d}"

        # 썸네일 처리
        if art.get("thumbnail_b64"):
            b64 = art["thumbnail_b64"]
            # mp4/webm은 <video>로 — img에 video data URL 넣으면 크롬에서 깨진 이미지로 표시됨.
            if b64.startswith("data:video/"):
                img_html = f'<div class="image-frame"><video class="article-image" src="{b64}" autoplay muted loop playsinline preload="metadata"></video></div>'
            else:
                img_html = f'<div class="image-frame"><img class="article-image" src="{b64}" alt="썸네일"></div>'
        else:
            img_html = '<div class="image-frame"><div class="no-thumb">썸네일 없음</div></div>'

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

    total = len(articles)
    last_2col = total % 2 or 2
    last_3col = total % 3 or 3

    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"><meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#1a1a1a" media="(prefers-color-scheme: dark)"><title>{DATE_DISPLAY} Trend Article Digest</title><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
  --img-bg:#fff; --cta-bg:#191919; --cta-text:#fff;
}}
@media (prefers-color-scheme:dark) {{
  :root {{
    --line:#2a2a2a; --text:#e8e8e8; --text2:#ccc; --text3:#aaa; --text4:#888; --text5:#777;
    --surface:#1a1a1a; --page:#111; --link-bg:rgba(60,140,240,0.12); --link-border:rgba(60,140,240,0.15); --link-text:#6ab0ff;
    --img-bg:#1a1a1a; --cta-bg:#e8e8e8; --cta-text:#111;
  }}
}}
html,body {{ width:100%; background:var(--surface); }}
body {{ font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,sans-serif; color:var(--text); }}
.page {{ width:100%; background:#fff; }}
.card {{ width:100%; max-width:100%; background:var(--surface); border-radius:8px; }}
.header {{ padding:28px 20px 24px; border-bottom:1px solid var(--line); }}
.header h1 {{ font-size:clamp(24px,3vw,30px); font-weight:600; line-height:1.2; letter-spacing:-0.02em; }}
.header-meta {{ margin-top:14px; font-size:16px; color:var(--text4); font-weight:500; line-height:1.6; }}
.article-wrap {{ padding:0 20px 0; }}
.article-item {{ padding:24px 0 28px; border-bottom:1px solid var(--line); }}
.article-item:last-of-type {{ border-bottom:0; padding-bottom:20px; }}
.article-label {{ display:inline-block; margin-bottom:14px; padding:7px 10px; background:var(--surface); border:1px solid var(--line); border-radius:8px; font-size:10px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase; color:var(--text5); }}
.article-title {{ font-size:clamp(24px,2.7vw,30px); font-weight:700; line-height:1.33; margin-bottom:10px; letter-spacing:-0.02em; word-break:keep-all; }}
.article-summary {{ font-size:clamp(15px,1.8vw,17px); font-weight:500; line-height:1.65; color:var(--text3); margin-bottom:18px; word-break:keep-all; }}
.image-frame {{ margin-bottom:18px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:var(--img-bg); }}
.article-image {{ width:100%; height:auto; display:block; background:var(--img-bg); border:0; border-radius:8px; object-fit:contain; object-position:center center; }}
.no-thumb {{ width:100%; aspect-ratio:16/10; display:flex; align-items:center; justify-content:center; background:var(--page); color:var(--text5); font-size:14px; }}
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
  .header{{padding:40px 32px 32px;}} .article-wrap{{padding:0 32px 0;}} .article-item{{padding:28px 0 32px;}}
  .article-item:last-of-type{{padding-bottom:40px;}}
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
  .image-frame {{ width: 100%; aspect-ratio: 16 / 10; overflow: hidden; border-radius: 8px; background: var(--img-bg); }}
  .image-frame .article-image {{ width: 100%; height: 100%; display: block; object-fit: cover; object-position: center center; }}
}}
@media (max-width: 1199px) {{
  .image-frame {{ aspect-ratio: auto; }}
  .image-frame .article-image {{ width: 100%; height: auto; display: block; object-fit: contain; object-position: center center; }}
}}
@media (min-width: 1200px) {{
  .article-item:nth-last-child(-n+{last_2col}) {{ border-bottom: none !important; padding-bottom: 0 !important; margin-bottom: 0 !important; }}
}}
@media (min-width: 1600px) {{
  .card {{ max-width: 1800px; }}
  .article-wrap {{ grid-template-columns: minmax(0,1fr) minmax(0,1fr) minmax(0,1fr); }}
  .article-item:nth-last-child(-n+{last_2col}) {{ border-bottom: 1px solid var(--line) !important; padding-bottom: 32px !important; margin-bottom: 0 !important; }}
  .article-item:nth-last-child(-n+{last_3col}) {{ border-bottom: none !important; padding-bottom: 0 !important; margin-bottom: 0 !important; }}
}}
.link-box a, .link-url, .article-link, .url-text {{
  display: block !important; width: 100% !important; min-width: 0 !important;
  overflow: hidden !important; white-space: nowrap !important; text-overflow: ellipsis !important;
}}
.agit-cta {{ margin: 0 20px; border-top: 1px solid var(--line); padding: 20px 0 28px; text-align: center; }}
.agit-cta-btn {{ display: flex; align-items: center; justify-content: center; width: 100%; height: 56px; background: var(--cta-bg); color: var(--cta-text) !important; border-radius: 8px; font-size: 15px; font-weight: 600; text-decoration: none; letter-spacing: -0.01em; }}
.agit-cta-btn:hover {{ opacity: 0.8; }}
@media (min-width: 768px) {{ .agit-cta {{ margin: 0 40px; padding: 40px 0 32px; }} .agit-cta-btn {{ display: inline-flex; width: auto; padding: 0 24px; }} }}
@media (min-width: 1200px) {{ .agit-cta {{ padding: 40px 0 36px; }} }}
</style></head><body><div class="page"><div class="card"><header class="header"><h1>{DATE_DISPLAY}</h1><div class="header-meta">Trend Article Digest</div></header><main class="article-wrap article-list">
{intro_html}
{cards_html}
</main><div class="agit-cta"><a class="agit-cta-btn" href="https://kakao.agit.in/g/300044281/wall">트렌드림 아지트로 돌아가기</a></div></div></div></body></html>"""

    return html


# ─── 메인 실행 ────────────────────────────────────────────────
def _extract_meta(html_text):
    """HTML에서 og:title, og:description 등 메타 정보 추출"""
    meta = {}
    if not html_text:
        return meta
    try:
        soup = BeautifulSoup(html_text, "lxml")
        for tag in soup.find_all("meta"):
            prop = tag.get("property", "") or tag.get("name", "")
            content = tag.get("content", "")
            if prop in ("og:title", "og:description", "og:site_name",
                        "description", "title", "twitter:title", "twitter:description"):
                meta[prop] = content
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            meta["page_title"] = title_tag.string.strip()
    except Exception:
        pass
    return meta


def _extract_text(html_text, max_len=3000):
    """HTML에서 본문 텍스트 추출"""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:max_len]


def summarize_single_article(url):
    """단일 기사를 Claude API로 요약"""
    client = anthropic.Anthropic(max_retries=8)

    html = fetch_page(url)
    page_text = _extract_text(html)

    # 텍스트가 너무 짧으면 Playwright로 직접 재시도
    if len(page_text) < 300 and _pw_available():
        print(f"  ⚠️  추출 텍스트 {len(page_text)}자로 부족, Playwright로 직접 재시도")
        pw_html = fetch_page_playwright(url)
        pw_text = _extract_text(pw_html)
        if len(pw_text) > len(page_text):
            page_text = pw_text
            print(f"  ✅ Playwright로 {len(page_text)}자 추출 성공")
        else:
            print(f"  ⚠️  Playwright로도 텍스트 부족 ({len(pw_text)}자)")

    # 본문 추출 완전 실패 시: URL 메타데이터 기반 요약 시도
    content_available = len(page_text) >= 300
    if not content_available:
        print(f"  🔄 본문 접근 불가 → URL 메타데이터 기반 요약 시도")
        # og:title, og:description 등 메타 정보 추출
        meta_info = _extract_meta(html) if html else {}
        meta_block = ""
        if meta_info:
            meta_block = "\n".join(f"- {k}: {v}" for k, v in meta_info.items() if v)

        # 메타 정보도 없어도 Claude가 URL 기반으로 추론 시도
        if not meta_block:
            print(f"  ⚠️  메타 정보도 없음 → Claude URL 기반 추론 시도")

    if content_available:
        content_section = f"기사 본문:\n{page_text}"
    else:
        domain = urlparse(url).netloc
        path_keywords = urlparse(url).path.replace("/", " ").replace("-", " ").replace("_", " ").strip()
        content_section = f"""기사 본문을 직접 가져올 수 없었습니다.
아래 정보를 모두 활용하여 해당 기사의 내용을 최대한 정확하게 추론하여 요약해주세요.
반드시 모든 필드를 채워주세요. 빈 값은 허용되지 않습니다.

사이트: {domain}
URL 경로 키워드: {path_keywords}
메타 정보: {meta_block if meta_block else '(없음)'}
전체 URL: {url}

위 URL의 사이트 특성, URL 경로에 포함된 키워드, 메타 정보를 종합하여
이 기사가 어떤 내용인지 추론해주세요. 해당 사이트의 일반적인 콘텐츠 유형과
URL 구조에서 파악 가능한 주제를 근거로 작성해주세요."""

    prompt = f"""아래 기사를 트렌드림 뉴스레터 형식으로 정리해주세요.

기사 URL: {url}
{content_section}

아래 JSON 형식으로 답변하세요. JSON만 출력:
```json
{{
  "url": "{url}",
  "title_ko": "한국어 제목 (원문 의미 최대한 살려 번역)",
  "one_line": "20자 내외 한 줄 요약. 명사형 + 마침표로 끝남",
  "summary_1": "첫 번째 요약 (약 100자, 해요체)",
  "summary_2": "두 번째 요약 (약 100자, 해요체)",
  "summary_3": "세 번째 요약 (약 100자, 해요체)"
}}
```

## 한 줄 요약 규칙
- 20자 내외, 명사형 + 마침표
- ~해요, ~입니다, ~했다, ~한 것 사용 금지

## 3줄 요약 규칙
- 각 줄 약 100자 내외, 해요체
- "이 글은", "이 기사는" 등 메타 문장 금지
- 핵심 내용부터 바로 시작"""

    # 최대 3회 시도 (JSON 파싱 실패 또는 빈 값 나오면 재시도)
    for attempt in range(3):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # 코드펜스(```json … ```) 우선, 없으면 최외곽 중괄호 매칭
        fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if fence_match:
            json_str = fence_match.group(1)
        else:
            brace_match = re.search(r'\{[\s\S]*\}', text)
            json_str = brace_match.group(0) if brace_match else None

        if not json_str:
            print(f"  ⚠️  JSON 블록을 찾을 수 없음 (시도 {attempt + 1}/3)")
            continue

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"  ⚠️  JSON 파싱 실패 (시도 {attempt + 1}/3): {e}")
            # LLM 출력에서 흔한 문제 보정 후 재시도: 제어문자 제거
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
            try:
                result = json.loads(cleaned)
                print(f"  ✅ 제어문자 제거 후 파싱 성공")
            except json.JSONDecodeError:
                continue

        # 필수 키 보정
        required_keys = ["url", "title_ko", "one_line", "summary_1", "summary_2", "summary_3"]
        for k in required_keys:
            if k not in result:
                result[k] = url if k == "url" else ""

        # 요약 품질 검증: 빈 값이나 너무 짧은 요약 체크
        summary_fields = ["title_ko", "one_line", "summary_1", "summary_2", "summary_3"]
        empty_fields = [k for k in summary_fields if len(result.get(k, "").strip()) < 5]
        if empty_fields and attempt < 2:
            print(f"  ⚠️  요약 품질 부족 (빈 필드: {empty_fields}) → 재시도")
            continue
        if empty_fields:
            print(f"  ⚠️  재시도 후에도 빈 필드: {empty_fields}")
            result["_needs_manual_patch"] = True
        if not content_available:
            # 본문 없이 추론한 경우 표시 (검수용)
            result["_inferred_from_url"] = True
        return result
    return None


def load_existing_articles():
    """오늘 날짜의 기존 HTML에서 기사 데이터를 추출"""
    archive_dir = "test" if TEST_MODE else TODAY.strftime("%Y-%m-%d")
    archive_path = f"{archive_dir}/index.html"
    if not os.path.exists(archive_path):
        print(f"❌ 기존 파일 없음: {archive_path} — 교체 모드는 기존 큐레이션이 필요합니다.")
        sys.exit(1)

    with open(archive_path, "r", encoding="utf-8") as f:
        content = f.read()

    soup = BeautifulSoup(content, "lxml")
    articles = []
    for item in soup.find_all("article", class_="article-item"):
        title = item.find(class_="article-title")
        summary = item.find(class_="article-summary")
        bullets = item.find_all(class_="bullet-item")
        link = item.find(class_="article-link")
        img = item.find(class_="article-image")

        art = {
            "title_ko": title.get_text(strip=True) if title else "",
            "one_line": summary.get_text(strip=True) if summary else "",
            "summary_1": bullets[0].get_text(strip=True) if len(bullets) > 0 else "",
            "summary_2": bullets[1].get_text(strip=True) if len(bullets) > 1 else "",
            "summary_3": bullets[2].get_text(strip=True) if len(bullets) > 2 else "",
            "url": link["href"] if link else "",
            "thumbnail_b64": img["src"] if img and img.get("src", "").startswith("data:") else None,
        }
        articles.append(art)

    print(f"📂 기존 기사 {len(articles)}개 로드 완료")
    return articles


def main():
    print("=" * 60)
    print("🚀 트렌드림 기사 큐레이션 자동화 시작")
    print("=" * 60)

    # ── 교체 모드 ──
    if REPLACEMENTS:
        print("\n🔄 기사 교체 모드 실행")
        existing = load_existing_articles()

        for num, new_url in REPLACEMENTS.items():
            idx = num - 1  # 0-based
            if idx < 0 or idx >= len(existing):
                print(f"⚠️  기사 {num}번은 범위 밖 (총 {len(existing)}개)")
                continue

            print(f"\n🔄 기사 {num}번 교체: {new_url}")
            new_art = summarize_single_article(new_url)
            if not new_art:
                print(f"  ❌ 요약 실패, 기존 기사 유지")
                continue

            # 썸네일 다운로드
            html = fetch_page(new_url)
            thumb_b64 = None
            if html:
                og_img = extract_og_image(html, new_url)
                if og_img:
                    thumb_b64 = download_image_as_base64(og_img, referer=new_url)

            new_art["thumbnail_b64"] = thumb_b64
            new_art["article_num"] = num
            existing[idx] = new_art
            print(f"  ✅ 교체 완료: {new_art.get('title_ko', '(제목 없음)')}")

        # 번호 재정렬
        for i, art in enumerate(existing, 1):
            art["article_num"] = i

        enriched = existing
    else:
        # ── 일반 모드 ──
        if CURATE_MODE == "legacy":
            print(f"\n🗂  CURATE_MODE=legacy — 기존 사이트 화이트리스트 스캔")
            # 1. 우선 사이트 스캔
            candidates = scan_priority_sites()
            print(f"\n📋 총 {len(candidates)}개 후보 기사 수집")
            # 2. Claude API로 기사 선정 + 요약
            articles = curate_with_claude(candidates)
        else:
            print(f"\n🌐 CURATE_MODE=web_search — Claude 인터넷 검색 큐레이션")
            articles = curate_via_web_search()

        # 기사 수 검증 — 여유분은 enrich 단계에서 ARTICLE_COUNT개까지만 채움
        if len(articles) < ARTICLE_COUNT:
            print(f"⚠️  중복 제거 후 {len(articles)}개 — 요청 {ARTICLE_COUNT}개 미달 가능")

        # 3. 각 기사 상세 + 썸네일 (차단 도메인 건너뛰며 ARTICLE_COUNT개 채움)
        enriched = enrich_articles(articles, ARTICLE_COUNT)

    # 4. HTML 생성
    html_content = generate_html(enriched)

    # 5. 파일 저장
    if not TEST_MODE:
        # index.html로 저장 (GitHub Pages 메인) — 테스트 모드에서는 건드리지 않음
        output_path = "index.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"\n💾 저장 완료: {output_path}")
    else:
        print(f"\n🧪 [TEST MODE] root index.html 변경 없음")

    # 날짜별 아카이브 저장 (기존 레포 구조: YYYY-MM-DD/index.html)
    # TEST_MODE일 경우 test/ 폴더에만 저장하고 root index.html은 덮어쓰지 않음
    if TEST_MODE:
        archive_dir = "test"
        os.makedirs(archive_dir, exist_ok=True)
        archive_path = f"{archive_dir}/index.html"
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"🧪 [TEST MODE] 저장 완료: {archive_path} (root index.html 변경 없음)")
    else:
        archive_dir = TODAY.strftime("%Y-%m-%d")
        os.makedirs(archive_dir, exist_ok=True)
        archive_path = f"{archive_dir}/index.html"
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"💾 아카이브 저장: {archive_path}")

    # 썸네일 실패 기사 목록
    failed = [a["article_num"] for a in enriched if not a.get("thumbnail_b64")]
    if failed:
        print(f"\n⚠️  썸네일 미확보 기사: {failed}")
        print("   → 수동으로 이미지를 제공하거나 placeholder가 표시됩니다.")

    # 수동 패치 필요 기사 목록
    manual_patch = [a["article_num"] for a in enriched if a.get("_needs_manual_patch")]
    if manual_patch:
        print(f"\n🚨 수동 패치 필요 기사: {manual_patch}")
        print("   → 본문 접근 불가 사이트입니다. Cowork에서 수동으로 요약을 입력해주세요.")
        for a in enriched:
            if a.get("_needs_manual_patch"):
                print(f"   기사 {a['article_num']}번: {a['url']}")

    print("\n" + "=" * 60)
    print("✅ 큐레이션 완료!")
    if manual_patch:
        print(f"⚠️  수동 패치 필요: {len(manual_patch)}개 기사")
    print("=" * 60)


if __name__ == "__main__":
    main()
