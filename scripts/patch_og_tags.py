#!/usr/bin/env python3
"""
특정 날짜 index.html에 OG 메타태그를 삽입하는 패치 스크립트.
- 첫 기사의 제목, 한 줄 요약, 썸네일을 추출
- 썸네일 base64를 thumb.png로 저장
- <head>에 OG 태그 삽입
"""
import os
import sys
import re
import base64
from bs4 import BeautifulSoup

REPO_BASE_URL = "https://leche.github.io/trend-articles"


def patch_og(date_folder):
    html_path = f"{date_folder}/index.html"
    if not os.path.exists(html_path):
        print(f"❌ 파일 없음: {html_path}")
        return False

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 이미 OG 태그 있는지 체크
    if 'property="og:title"' in html:
        print(f"⏩ 이미 OG 태그 있음: {html_path}")
        return False

    soup = BeautifulSoup(html, "lxml")

    # 첫 번째 article 찾기
    first_article = soup.find("article", class_="article-item")
    if not first_article:
        print(f"❌ article 못 찾음: {html_path}")
        return False

    # 제목
    title_tag = first_article.find("h2", class_="article-title")
    first_title = title_tag.get_text(strip=True) if title_tag else ""

    # 한 줄 요약
    summary_tag = first_article.find("p", class_="article-summary")
    first_summary = summary_tag.get_text(strip=True) if summary_tag else ""

    # 썸네일 (base64)
    img_tag = first_article.find("img", class_="article-image")
    thumb_saved = False
    if img_tag and img_tag.get("src", "").startswith("data:image"):
        src = img_tag["src"]
        # data:image/png;base64,XXXX 파싱
        match = re.match(r"data:image/(\w+);base64,(.+)", src)
        if match:
            ext = match.group(1)
            b64_data = match.group(2)
            thumb_path = f"{date_folder}/thumb.{ext}"
            with open(thumb_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            thumb_ext = ext
            thumb_saved = True
            print(f"  ✅ 썸네일 저장: {thumb_path}")

    # OG 태그 생성
    page_url = f"{REPO_BASE_URL}/{date_folder}/"
    og_title = soup.title.string if soup.title else f"{date_folder} Trend Article Digest"
    og_description = f"{first_title} — {first_summary}" if first_summary else first_title
    og_image_url = f"{page_url}thumb.{thumb_ext}" if thumb_saved else ""

    og_tags = f'''<meta property="og:type" content="article">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_description}">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="트렌드림">'''
    if og_image_url:
        og_tags += f'\n<meta property="og:image" content="{og_image_url}">'
    og_tags += '\n<meta name="twitter:card" content="summary_large_image">'

    # <title> 태그 바로 뒤에 OG 태그 삽입
    new_html = html.replace(
        f"<title>{og_title}</title>",
        f"<title>{og_title}</title>{og_tags}"
    )

    if new_html == html:
        # title 매칭 실패 시 </head> 앞에 삽입
        new_html = html.replace("</head>", f"{og_tags}</head>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"✅ OG 태그 삽입 완료: {html_path}")
    print(f"   og:title       = {og_title}")
    print(f"   og:description = {og_description}")
    print(f"   og:image       = {og_image_url or '(없음)'}")
    print(f"   og:url         = {page_url}")
    return True


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-04-10"
    patch_og(date)
