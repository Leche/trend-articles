#!/usr/bin/env python3
"""6번 기사(wiseapp) 내용을 수동으로 패치하는 스크립트 — BeautifulSoup 사용"""
import os
import datetime
from bs4 import BeautifulSoup

# 6번 기사 데이터 (Chrome 브라우저에서 직접 확인한 내용 기반)
TITLE = "26년 2월 금융 앱 동향: 한국인이 가장 많이 사용하는 금융 결제 앱은?"
ONE_LINE = "금융 결제 앱 사용 현황 분석."
SUMMARY_1 = "25년 9월~26년 2월 기준, 한국인이 가장 많이 사용한 금융 결제 앱은 토스(2,554만 명), 삼성 월렛(1,911만 명), 카카오뱅크(1,824만 명) 순이었어요."
SUMMARY_2 = "1인당 평균 사용시간은 토스가 1시간 58분으로 압도적이었고, 카카오페이(35분), 네이버페이(25분)가 뒤를 이었어요. 금융 슈퍼앱의 체류시간이 결제 앱보다 훨씬 길었어요."
SUMMARY_3 = "40대 이하에서는 토스, 50대 이상에서는 삼성 월렛 사용자가 가장 많았어요. 결제 앱은 점심시간에 집중되는 반면, 금융 슈퍼앱은 오후 6시 이후에도 활발하게 사용되고 있어요."


def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"  ❌ 파일 없음: {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        original = f.read()

    soup = BeautifulSoup(original, "html.parser")

    # ARTICLE 06 라벨이 있는 article-item 찾기
    target_article = None
    for label_div in soup.find_all("div", class_="article-label"):
        if "ARTICLE 06" in label_div.get_text():
            target_article = label_div.find_parent("article")
            break

    if not target_article:
        print(f"  ⚠️  ARTICLE 06 못 찾음: {filepath}")
        return False

    # 제목 교체
    title_el = target_article.find("h2", class_="article-title")
    if title_el:
        title_el.string = TITLE
        print(f"  제목 → {TITLE[:30]}...")

    # 한 줄 요약 교체
    summary_el = target_article.find("p", class_="article-summary")
    if summary_el:
        summary_el.string = ONE_LINE
        print(f"  한줄요약 → {ONE_LINE}")

    # 3줄 요약 교체 (bullet-list > bullet-item)
    bullet_list = target_article.find("ul", class_="bullet-list")
    if bullet_list:
        items = bullet_list.find_all("li")
        summaries = [SUMMARY_1, SUMMARY_2, SUMMARY_3]
        for i, item in enumerate(items):
            if i < len(summaries):
                item.string = summaries[i]
                print(f"  요약{i+1} → {summaries[i][:40]}...")

    # BeautifulSoup 결과를 원본 포맷 유지하며 저장
    # soup.decode()는 원본 HTML 구조를 유지함
    result = str(soup)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)

    print(f"  ✅ 패치 완료: {filepath}")
    return True


if __name__ == "__main__":
    today = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    ).date()
    date_str = today.strftime("%Y-%m-%d")

    files_patched = 0
    for path in [f"{date_str}/index.html", "index.html"]:
        if patch_file(path):
            files_patched += 1

    print(f"\n총 {files_patched}개 파일 패치됨")
