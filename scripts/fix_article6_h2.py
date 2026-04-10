#!/usr/bin/env python3
"""6번 기사의 깨진 h2 태그를 복원하는 스크립트"""
import os, datetime

BROKEN = 'V년 2월 금융 앱 동향: 한국인이 가장 많이 사용하는 금융 결제 앱은?'
FIXED = '<h2 class="article-title">26년 2월 금융 앱 동향: 한국인이 가장 많이 사용하는 금융 결제 앱은?</h2>'

def fix_file(filepath):
    if not os.path.exists(filepath):
        print(f"  파일 없음: {filepath}")
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    if BROKEN not in content:
        print(f"  깨진 텍스트 못 찾음: {filepath}")
        return False
    new_content = content.replace(BROKEN, FIXED)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  h2 복원 완료: {filepath}")
    return True

if __name__ == "__main__":
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    date_str = today.strftime("%Y-%m-%d")
    fixed = 0
    for path in [f"{date_str}/index.html", "index.html"]:
        if fix_file(path):
            fixed += 1
    print(f"총 {fixed}개 파일 수정됨")
