#!/usr/bin/env python3
"""6번 기사(wiseapp) 내용을 수동으로 패치하는 스크립트"""
import re
import os

# 6번 기사 데이터 (Chrome 브라우저에서 직접 확인한 내용 기반)
ARTICLE_6 = {
    "title_ko": "26년 2월 금융 앱 동향: 한국인이 가장 많이 사용하는 금융 결제 앱은?",
    "one_line": "금융 결제 앱 사용 현황 분석.",
    "summary_1": "25년 9월~26년 2월 기준, 한국인이 가장 많이 사용한 금융 결제 앱은 토스(2,554만 명), 삼성 월렛(1,911만 명), 카카오뱅크(1,824만 명) 순이었어요.",
    "summary_2": "1인당 평균 사용시간은 토스가 1시간 58분으로 압도적이었고, 카카오페이(35분), 네이버페이(25분)가 뒤를 이었어요. 금융 슈퍼앱의 체류시간이 결제 앱보다 훨씬 길었어요.",
    "summary_3": "40대 이하에서는 토스, 50대 이상에서는 삼성 월렛 사용자가 가장 많았어요. 결제 앱은 점심시간에 집중되는 반면, 금융 슈퍼앱은 오후 6시 이후에도 활발하게 사용되고 있어요.",
    "url": "https://www.wiseapp.co.kr/insight/detail/962/2026-finance-bank-payment-creditcard-local-currency-app-trend"
}


def patch_file(filepath):
    """index.html 파일에서 ARTICLE 06 섹션의 빈 내용을 채움"""
    if not os.path.exists(filepath):
        print(f"  ❌ 파일 없음: {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    if "ARTICLE 06" not in html:
        print(f"  ⚠️  ARTICLE 06이 없음: {filepath}")
        return False

    # 기사 제목 패치 (빈 h2 또는 접근 불가 제목)
    # ARTICLE 06 라벨 이후의 첫 번째 h2 태그를 찾아서 교체
    # 패턴: ARTICLE 06 이후 ~ ARTICLE 07 또는 파일 끝 사이의 콘텐츠

    # 방법: ARTICLE 06 블록을 찾고, 그 안의 내용들을 교체
    # article-card 블록 기반으로 처리

    parts = html.split("ARTICLE 06")
    if len(parts) < 2:
        print(f"  ⚠️  ARTICLE 06 분할 실패")
        return False

    before = parts[0]
    after_06 = parts[1]

    # ARTICLE 06 뒤의 블록에서 다음 ARTICLE이 나올 때까지가 6번 기사 영역
    # 제목 교체
    # 빈 제목 또는 "기사 본문 내용 없음" 등을 실제 제목으로 교체
    after_06 = re.sub(
        r'(<h2[^>]*class="article-title"[^>]*>)(.*?)(</h2>)',
        rf'\1{ARTICLE_6["title_ko"]}\3',
        after_06,
        count=1,
        flags=re.DOTALL
    )

    # 한 줄 요약 교체
    after_06 = re.sub(
        r'(<p[^>]*class="one-line-summary"[^>]*>)(.*?)(</p>)',
        rf'\1{ARTICLE_6["one_line"]}\3',
        after_06,
        count=1,
        flags=re.DOTALL
    )

    # 3줄 요약 교체 (ul > li 구조)
    # 첫 3개 li 태그를 교체
    li_count = 0
    summaries = [ARTICLE_6["summary_1"], ARTICLE_6["summary_2"], ARTICLE_6["summary_3"]]

    def replace_li(match):
        nonlocal li_count
        if li_count < 3:
            result = f'{match.group(1)}{summaries[li_count]}{match.group(3)}'
            li_count += 1
            return result
        return match.group(0)

    # 요약 리스트의 li만 교체 (SUMMARY 라벨 이후)
    summary_split = after_06.split("SUMMARY", 1)
    if len(summary_split) == 2:
        summary_part = summary_split[1]
        # 다음 article-card나 link-box 전까지의 li들만 교체
        summary_part = re.sub(
            r'(<li[^>]*>)(.*?)(</li>)',
            replace_li,
            summary_part,
            flags=re.DOTALL
        )
        after_06 = summary_split[0] + "SUMMARY" + summary_part

    html = before + "ARTICLE 06" + after_06

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅ 패치 완료: {filepath}")
    return True


if __name__ == "__main__":
    import datetime

    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    date_str = today.strftime("%Y-%m-%d")

    files_patched = 0
    for path in [f"{date_str}/index.html", "index.html"]:
        if patch_file(path):
            files_patched += 1

    print(f"\n총 {files_patched}개 파일 패치됨")
