#!/usr/bin/env python3
"""
과거 날짜별 index.html에 다크모드 CSS를 일괄 적용하는 스크립트.
git repo 루트에서 실행: python scripts/patch_darkmode.py
"""
import os
import re
import glob

# 다크모드 변수 + 추가 변수
OLD_ROOT = """:root {
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
}"""

NEW_ROOT = """:root {
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
  --body-bg:#fff; --label-bg:#fbfbfb; --img-bg:#fff; --placeholder-bg:#f5f5f5; --placeholder-text:#bbb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --line:#2C2C2C; --text:#E8E8E8; --text2:#D0D0D0; --text3:#A0A0A0; --text4:#777; --text5:#666;
    --surface:#1E1E1E; --page:#121212; --link-bg:rgba(64,156,255,0.12); --link-border:rgba(64,156,255,0.15); --link-text:#409CFF;
    --body-bg:#121212; --label-bg:#2A2A2A; --img-bg:#1E1E1E; --placeholder-bg:#2A2A2A; --placeholder-text:#666;
  }
}"""

# 하드코딩 색상 교체 매핑
REPLACEMENTS = [
    ("html,body { width:100%; background:#fff; }",
     "html,body { width:100%; background:var(--body-bg); }"),
    (".page { width:100%; background:#fff; }",
     ".page { width:100%; background:var(--body-bg); }"),
    ("background:#fbfbfb;",
     "background:var(--label-bg);"),
    (".image-frame { margin-bottom:18px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:#fff; }",
     ".image-frame { margin-bottom:18px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:var(--img-bg); }"),
    ("background:#fff; border:0;",
     "background:var(--img-bg); border:0;"),
    ("background: #fff; }",
     "background: var(--img-bg); }"),
    ("background:#f5f5f5; color:#bbb;",
     "background:var(--placeholder-bg); color:var(--placeholder-text);"),
]


def patch_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()

    if 'prefers-color-scheme' in html:
        return False  # 이미 적용됨

    if OLD_ROOT not in html:
        return False  # 구조가 다른 파일

    html = html.replace(OLD_ROOT, NEW_ROOT)
    for old, new in REPLACEMENTS:
        html = html.replace(old, new)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return True


def main():
    # 날짜별 폴더 찾기
    folders = sorted(glob.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]/index.html"))

    if not folders:
        print("❌ 날짜별 index.html 파일을 찾을 수 없어요. git repo 루트에서 실행해주세요.")
        return

    patched = []
    skipped = []
    for path in folders:
        if patch_file(path):
            patched.append(path)
            print(f"  ✅ {path}")
        else:
            skipped.append(path)
            print(f"  ⏩ {path} (이미 적용 또는 구조 다름)")

    print(f"\n✅ 완료: {len(patched)}개 적용, {len(skipped)}개 건너뜀")

    if patched:
        print("\n📋 git 커밋 명령:")
        print(f'  git add {" ".join(patched)} && git commit -m "feat: apply dark mode to {len(patched)} past article pages" && git pull --rebase && git push')


if __name__ == "__main__":
    main()
