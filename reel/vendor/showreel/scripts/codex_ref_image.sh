#!/usr/bin/env bash
# 참조 이미지(실제 사진)를 붙여 같은 인물·동물·제품이 '새 장면'에 나오는 이미지를 codex 로 만든다.
# codex-image 배치 스크립트는 참조 이미지를 받지 않으므로 이 래퍼를 쓴다.
#
# 사용법: codex_ref_image.sh <out.png> "<장면 프롬프트>" <ref1.jpg> [ref2.jpg ...]
#   - out.png 의 폴더가 작업 폴더가 된다(프로젝트 안, 예: assets/gen/).
#   - 참조 사진은 긴 변 1024px 정도로 줄여 두면 빠르다(sips -Z 1024 in.jpg --out ref.jpg).
#   - 프롬프트에는 대상의 신원 특징(무늬·눈 색·옷·소품)을 글로 다시 적고, 비율("가로 16:9 구도")과 "글자·로고 없음"을 넣는다.
#   - 여러 장은 Bash run_in_background 로 최대 5개까지 동시에 돌린다(그 이상은 대기열이 생겨 느려진다).
#   - 이미 out.png 가 있으면 건너뛴다(실패한 것만 다시 돌리기 쉽게).
set -u
OUT="$1"; PROMPT="$2"; shift 2
[ -s "$OUT" ] && { echo "SKIP $OUT"; exit 0; }
DIR="$(cd "$(dirname "$OUT")" && pwd)"; NAME="$(basename "$OUT")"
mkdir -p "$DIR/.codex-logs"
IMGS=()
for r in "$@"; do IMGS+=(-i "$(cd "$(dirname "$r")" && pwd)/$(basename "$r")"); done
BASE="첨부한 실제 사진 속 대상의 생김새·무늬·체형·고유한 특징을 최대한 그대로 유지한 채, 같은 대상으로 보이는 새로운 이미지를 이미지 생성 도구로 만들어라. 첨부 사진을 복사하거나 편집하지 말고 아래 장면을 새로 찍은 것처럼 생성할 것."
START=$(date +%s)
codex exec --sandbox workspace-write --skip-git-repo-check --cd "$DIR" "${IMGS[@]}" -o "$DIR/.codex-logs/${NAME%.*}.md" \
  "$BASE

장면: $PROMPT

생성한 이미지를 반드시 ./$NAME 파일로 저장(PNG). 저장 후 파일 경로만 한 줄로 보고." > "$DIR/.codex-logs/${NAME%.*}.out" 2>&1 < /dev/null
END=$(date +%s)
if [ -s "$OUT" ]; then echo "OK $OUT $((END-START))s"; else echo "FAIL $OUT $((END-START))s (로그: $DIR/.codex-logs/${NAME%.*}.out — 'at capacity' 면 다시 실행)"; exit 1; fi
