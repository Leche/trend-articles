#!/usr/bin/env python3
"""
모든 index.html에 다크모드 CSS를 일괄 적용하는 스크립트.
git repo 루트에서 실행: python3 scripts/patch_darkmode.py
"""
import os
import glob

# ── 패치 대상: :root에 다크모드 변수가 없는 파일 ──

# 기존 :root (다크모드 없는 버전)
OLD_ROOT = """:root {
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
}"""

NEW_ROOT = """:root {
  --line:#ededed; --text:#191919; --text2:#333; --text3:#555; --text4:#888; --text5:#999;
  --surface:#fff; --page:#f0f0f0; --link-bg:rgba(10,115,220,0.08); --link-border:rgba(10,115,220,0.08); --link-text:#0A73DC;
  --img-bg:#fff; --cta-bg:#191919; --cta-text:#fff;
}
@media (prefers-color-scheme:dark) {
  :root {
    --line:#2a2a2a; --text:#e8e8e8; --text2:#ccc; --text3:#aaa; --text4:#888; --text5:#777;
    --surface:#1a1a1a; --page:#111; --link-bg:rgba(60,140,240,0.12); --link-border:rgba(60,140,240,0.15); --link-text:#6ab0ff;
    --img-bg:#1a1a1a; --cta-bg:#e8e8e8; --cta-text:#111;
  }
}"""

# 하드코딩 색상 → CSS 변수로 교체
REPLACEMENTS = [
    # html,body 배경
    ("html,body { width:100%; background:#fff; }",
     "html,body { width:100%; background:var(--surface); }"),
    # page 배경
    (".page { width:100%; background:#fff; }",
     ".page { width:100%; background:var(--surface); }"),
    # article-label 배경
    ("background:#fbfbfb;", "background:var(--surface);"),
    # image-frame 배경
    ("border-radius:8px; background:#fff; }",
     "border-radius:8px; background:var(--img-bg); }"),
    ("background:#fff; border:0;",
     "background:var(--img-bg); border:0;"),
    ("background: #fff; }",
     "background: var(--img-bg); }"),
    # CTA 버튼
    ("background: #191919; color: #fff !important;",
     "background: var(--cta-bg); color: var(--cta-text) !important;"),
    ("background:#191919; color:#fff !important;",
     "background:var(--cta-bg); color:var(--cta-text) !important;"),
    # 썸네일 없음 placeholder → 클래스로
    ('style="width:100%;aspect-ratio:16/10;background:#f5f5f5;display:flex;align-items:center;justify-content:center;color:#999;font-size:14px;"',
     'class="no-thumb"'),
    ('style="width:100%;aspect-ratio:16/10;background:#f5f5f5;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:14px;"',
     'class="no-thumb"'),
]

NO_THUMB_CSS = ".no-thumb { width:100%; aspect-ratio:16/10; display:flex; align-items:center; justify-content:center; background:var(--page); color:var(--text5); font-size:14px; }\n"


def patch_file(path):
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    if "prefers-color-scheme" in html:
        return False  # 이미 적용됨

    if OLD_ROOT not in html:
        return False  # 구조가 다른 파일

    original = html

    # :root 교체
    html = html.replace(OLD_ROOT, NEW_ROOT)

    # 하드코딩 색상 교체
    for old, new in REPLACEMENTS:
        html = html.replace(old, new)

    # .no-thumb CSS 추가
    if ".no-thumb" in html and ".no-thumb {" not in html and ".summary-label" in html:
        html = html.replace(".summary-label", NO_THUMB_CSS + ".summary-label")

    if html == original:
        return False

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return True


def main():
    targets = ["index.html"]
    targets += sorted(glob.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]/index.html"))

    if not targets:
        print("파일을 찾을 수 없어요. git repo 루트에서 실행해주세요.")
        return

    patched = []
    skipped = []
    for path in targets:
        if not os.path.exists(path):
            continue
        if patch_file(path):
            patched.append(path)
            print(f"  ✅ {path}")
        else:
            skipped.append(path)
            print(f"  ⏩ {path} (이미 적용 또는 구조 다름)")

    print(f"\n총 {len(patched)}개 적용, {len(skipped)}개 건너뜀")


if __name__ == "__main__":
    main()
