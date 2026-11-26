#!/usr/bin/env python3
"""트렌드림 아침 브리핑 영상 생성기 (2026-11-27).

다이제스트 폴더(YYYY-MM-DD/index.html 의 agit-digest-data) → 진행자 대본 → Hani 나레이션(한 테이크)
→ 기사 단위로 자르기 → D 곡 반복 위에 박자 맞춤 배치 → 실사 클립 프레임 추출 → 렌더 → 믹스 → 웹용 mp4.

사용
  python3 reel/build.py --date 2026-11-27 [--work reel/_work/2026-11-27] [--from script|voice|place|plan|render]
  단계 결과는 작업 폴더에 캐시된다. --from 을 주면 그 단계부터 다시 한다(앞 단계 결과는 재사용).
환경
  ELEVENLABS_API_KEY · PIXABAY_API_KEY(없으면 ~/.config/pixabay/api-key) · LLM_BACKEND(api|cli, scripts/llm.py)
  REEL_SUB(모션 블러 서브프레임, 기본 2) · REEL_CLIP_CACHE(클립 원본 캐시, 기본 ~/.cache/trenddream-reel/clips)
결과
  <work>/out/reel.mp4(웹용 1080p) · <work>/out/meta.json
"""
import argparse, datetime, difflib, json, math, os, re, shutil, subprocess, sys, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
V = ROOT / "vendor/showreel/scripts"
sys.path.insert(0, str(V))
sys.path.insert(0, str(REPO / "scripts"))
import eleven  # noqa: E402

VOICE = "Ldr6pbPAWs2LIP4OPHYn"            # Hani (리체 선택)
TTS_MODEL = "eleven_v3"
TTS_SETTINGS = {"stability": 0.5, "similarity_boost": 0.8}
LLM_MODEL = os.environ.get("REEL_MODEL", "claude-opus-5-5")
FULL_COUNT = 5                            # agit-post.yml 과 같다: 1~5 본문형, 나머지는 "이것도 함께 실렸어요"
FPS = 30
MUSIC = ROOT / "assets/music_D.mp3"       # 리체가 고른 칠 트랩 샘플 D(30초)
BEAT0, BAR = 0.41, 1.6                    # D 곡 첫 다운비트·마디 길이(150 BPM)
LOOP_A, LOOP_B, END_B = 3.61, 22.81, 30.04
GRADE = ("curves=all='0/0 0.55/0.52 1/0.9',eq=contrast=1.05:saturation=0.84:gamma=0.98,"
         "colorbalance=rs=-0.03:gs=-0.005:bs=0.035:rh=0.03:gh=0.01:bh=-0.03")
WEEK = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
OUTRO = "오늘 브리핑은 여기까지예요. 기사 전체는 아지트 본문에서 읽어 보세요."
BRANCH = "이것도 함께 실렸어요."


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(map(str, cmd))[:200]}\n{r.stderr[-1500:]}")
    return r.stdout


def sino(n):
    """정수 → 한자어 수 읽기(1~9999)."""
    d = "영일이삼사오육칠팔구"
    if n == 0:
        return "영"
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 and name else d[q]) + name
    return out


# ─── 1. 다이제스트 읽기 ──────────────────────────────────────
def load_digest(date):
    html = (REPO / date / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="agit-digest-data" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit(f"{date}/index.html 에 agit-digest-data 가 없다")
    return json.loads(m.group(1))


# ─── 2. 대본(LLM) ────────────────────────────────────────────
SCRIPT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["hook", "articles"],
    "properties": {
        "hook": {"type": "object", "additionalProperties": False, "required": ["text", "tts", "lines"],
                 "properties": {"text": {"type": "string"}, "tts": {"type": "string"},
                                "lines": {"type": "array", "items": {"type": "string"}}}},
        "articles": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["num", "text", "tts", "head", "key", "cap", "key_tts", "clips"],
            "properties": {"num": {"type": "integer"}, "text": {"type": "string"}, "tts": {"type": "string"},
                           "head": {"type": "string"}, "key": {"type": "string"}, "cap": {"type": "string"},
                           "key_tts": {"type": "string"}, "clips": {"type": "array", "items": {"type": "integer"}}}}},
    },
}


def write_script(dg, clips, date):
    from llm import create, client, log_usage
    arts = dg["articles"]
    lib = [c for c in clips if c["cat"] not in ("open", "ending", "transit")]
    lines = "\n".join(f"- {c['id']} [{c['cat']}] {c['desc']}" for c in lib)
    art_txt = "\n".join(
        f"{a['num']}. 제목: {a.get('title','')}\n   헤드라인: {a.get('headline','')}\n   의미: {a.get('so_what','')}\n   출처: {a.get('link','')}"
        for a in arts)
    prompt = f"""트렌드림 아침 브리핑 영상의 나레이션 대본과 화면 문구를 써 주세요. 사내 크루가 아침에 보는 2분 30초 안팎의 IT·디자인 뉴스 영상이고, 차분한 여성 진행자가 읽어요.

[오늘 다이제스트 인트로]
{dg.get('intro','')}

[기사 {len(arts)}개 — 1~{FULL_COUNT}번은 본문 기사, 그 뒤는 "이것도 함께 실렸어요" 기사]
{art_txt}

[클립 라이브러리 — 기사마다 화면에 깔 실사 영상 2개를 여기서 고른다]
{lines}

[작성 규칙]
- 말투는 해요체 진행자. 문장은 짧게. 형용사보다 사실.
- 위에 적힌 제목·헤드라인·의미에 있는 사실만 쓴다. 새로운 숫자나 사실을 지어내지 않는다.
- hook: 인트로를 한 문장(45자 안팎)으로. 오늘 소식들을 묶는 관점. lines 는 같은 문장을 화면용 2~3줄로 나눈 것(줄당 16자 이하, 이어 붙이면 text 와 같다).
- articles: 기사마다 2~3문장, 화면 표기 기준 60~95자. 첫 문장은 누가 무엇을 했는지, 다음 문장은 왜 중요한지.
  1번은 "첫 소식은 …"으로 시작하고, 마지막 기사는 "마지막은 …"으로 시작한다. 전체 합계 900자를 넘지 않는다.
- tts: text 와 같은 문장을 소리 나는 대로. 숫자·%·연도·영문 약어·영문 브랜드는 한글 발음으로(2,900만→이천구백만, 32%→삼십이 퍼센트, AI→에이아이, X→엑스).
  쉼표·마침표의 개수와 위치는 text 와 똑같이 유지한다(자막 시각을 맞추는 데 쓴다).
- head: 화면 하단 타이틀. "주체, 핵심" 형식 22자 이하.
- key: 기사의 핵심이 진짜 숫자일 때만(예: "2,900만 곡", "32%", "1시간"). 숫자가 아니면 빈 문자열. cap 은 그 숫자 설명 18자 이하(숫자 없으면 빈 문자열).
- key_tts: key 가 있을 때 tts 안에서 그 숫자를 읽는 부분 문자열을 그대로 옮긴다(예: "이천구백만"). 없으면 빈 문자열.
- clips: 라이브러리에서 내용과 어울리는 서로 다른 id 2개. 같은 클립을 여러 기사에 쓰지 않는다. people 분류는 꼭 맞을 때만.
- num 은 기사 번호 그대로, 기사 순서대로 모두 쓴다."""
    resp = create(client(), model=LLM_MODEL, max_tokens=8000,
                  output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}, "effort": "medium"},
                  messages=[{"role": "user", "content": prompt}])
    log_usage("영상 대본", resp)
    text = next((b.text for b in resp.content if b.type == "text"), "")
    sc = json.loads(text)
    ids = {c["id"] for c in lib}
    used = set()
    for a in sc["articles"]:
        ok = [c for c in a["clips"] if c in ids and c not in used][:2]
        for c in lib:                                    # 모자라면 라이브러리에서 안 쓴 것으로 채운다
            if len(ok) >= 2:
                break
            if c["id"] not in used and c["id"] not in ok and c["cat"] != "people":
                ok.append(c["id"])
        a["clips"] = ok; used.update(ok)
        if a["key"] and a["key_tts"] not in a["tts"]:
            a["key"] = a["cap"] = a["key_tts"] = ""
    return sc


# ─── 3. 나레이션(한 테이크) ──────────────────────────────────
def paragraphs(sc, date):
    d = datetime.date.fromisoformat(date)
    paras = [{"id": "intro", "text": f"{d.month}월 {d.day}일 {WEEK[d.weekday()]}, 트렌드림 아침 브리핑이에요. {sc['hook']['text']}",
              "tts": f"{sino(d.month)}월 {sino(d.day)}일 {WEEK[d.weekday()]}, 트렌드림 아침 브리핑이에요. {sc['hook']['tts']}"}]
    for a in sc["articles"]:
        if a["num"] == FULL_COUNT + 1:
            paras.append({"id": "branch", "text": BRANCH, "tts": BRANCH})
        paras.append({"id": f"a{a['num']}", "text": a["text"], "tts": a["tts"]})
    paras.append({"id": "outro", "text": OUTRO, "tts": OUTRO})
    return paras


def norm(s):
    return re.sub(r"[\s\.,!?·…'\"%:;~\-]", "", s.lower())


def voice(paras, work, max_takes=2):
    full = "\n\n".join(p["tts"] for p in paras)
    best = None
    for k in range(max_takes):
        out = work / "audio/take" / f"take{k}.mp3"; out.parent.mkdir(parents=True, exist_ok=True)
        eleven.tts(full, str(out), voice=VOICE, model=TTS_MODEL, settings=TTS_SETTINGS, seed=7 + 12 * k, timestamps=True)
        got = eleven.stt(str(out)).get("text", "")
        want = " ".join(p["text"] for p in paras)
        sim = max(difflib.SequenceMatcher(None, norm(got), norm(want)).ratio(),
                  difflib.SequenceMatcher(None, norm(got), norm(full)).ratio())
        print(f"   🎙  테이크 {k}: 받아쓰기 유사도 {sim:.3f}")
        if best is None or sim > best[0]:
            best = (sim, out)
        if sim >= 0.96:
            break
    if best[0] < 0.9:
        raise RuntimeError(f"나레이션 받아쓰기 유사도가 낮다({best[0]:.3f}) — 대본 발음 표기를 확인")
    return best[1]


def split_take(take, paras, work):
    """문단 경계의 가장 조용한 지점에서 자른다(글자 정렬 시각은 첫소리보다 늦게 찍힐 때가 있다)."""
    import numpy as np
    al = json.loads(take.with_suffix(".align.json").read_text())
    ch, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    full = "".join(ch)
    x = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(take), "-ac", "1", "-ar", "44100", "-f", "f32le", "-"],
                                     capture_output=True).stdout, dtype=np.float32)
    sr = 44100; T = len(x) / sr; win = int(0.03 * sr); hop = int(0.005 * sr)

    def quietest(a, b):
        best, bt = 1e9, (a + b) / 2
        for s in range(int(a * sr), max(int(a * sr) + 1, int(b * sr) - win), hop):
            e = float(np.mean(x[s:s + win] ** 2))
            if e < best:
                best, bt = e, (s + win / 2) / sr
        return bt
    pos, spans = 0, []
    for p in paras:
        t = p["tts"].strip()
        i = full.index(t[:12], pos); j = i + len(t) - 1
        j = min(j, len(full) - 1); pos = j + 1; spans.append((i, j))
    cuts = [0.0] + [quietest(st[spans[k][1]] + 0.05, max(st[spans[k + 1][0]] + 0.05, st[spans[k][1]] + 0.15))
                    for k in range(len(spans) - 1)] + [T]
    vo = work / "audio/vo"; vo.mkdir(parents=True, exist_ok=True); rep = {}
    for k, p in enumerate(paras):
        i, j = spans[k]; a, b = cuts[k], cuts[k + 1]
        sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(take), "-ac", "1",
            "-af", f"afade=t=in:d=0.006,afade=t=out:st={max(0, b - a - 0.008):.3f}:d=0.008", "-c:a", "libmp3lame", "-b:a", "192k", str(vo / f"{p['id']}.mp3")])
        (vo / f"{p['id']}.align.json").write_text(json.dumps({
            "characters": ch[i:j + 1], "character_start_times_seconds": [round(v - a, 3) for v in st[i:j + 1]],
            "character_end_times_seconds": [round(v - a, 3) for v in en[i:j + 1]]}, ensure_ascii=False))
        rep[p["id"]] = {"file": f"{p['id']}.mp3", "dur": round(b - a, 3), "speech_start": round(max(0, st[i] - a - 0.08), 3),
                        "speech_end": round(min(b - a, en[j] - a + 0.05), 3), "ok": True, "tts": p["tts"]}
    (vo / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


# ─── 4. 배치(음악·타임라인) ──────────────────────────────────
def place(paras, rep, sc, work):
    nxt = lambda t: BEAT0 + BAR * math.ceil(max(0.0, t - BEAT0) / BAR - 1e-9)
    lines, prev = [], None
    keys = {f"a{a['num']}": a for a in sc["articles"]}
    for p in paras:
        r = rep[p["id"]]
        at = (nxt(0.9) if prev is None else nxt(prev + 0.9)) - r["speech_start"]
        prev = at + r["speech_end"]
        cues = {}
        if p["id"] == "intro":
            cues = {"brand": "트렌드림", "hook": sc["hook"]["tts"].split()[0]}
        elif p["id"] == "branch":
            cues = {"branch": "함께"}
        elif p["id"] == "outro":
            cues = {"end": "여기까지예요"}
        elif keys[p["id"]]["key_tts"]:
            cues = {f"k{p['id'][1:]}": keys[p["id"]]["key_tts"]}
        lines.append({"id": p["id"], "text": p["text"], "tts": p["tts"], "at": round(at, 3), "cues": cues, "nosub": True})
    # 비트 구간을 4마디(6.4초) 단위로 늘린다. 끝맺음(7.2초, 화음이 울리며 사라짐)이 마지막 인사 끝 + 3.5초를 덮게.
    PHRASE = BAR * 4
    n4 = max(1, math.ceil((prev + 3.5 - (END_B - LOOP_B) - LOOP_A) / PHRASE))
    k, m = divmod(n4, 3)                                                  # 12마디 루프 k번 + 4마디 m개
    loop_end = LOOP_A + PHRASE * n4
    duration = round(max(prev + 3.5, loop_end + 6.4), 2)
    mdir = work / "audio/music"; mdir.mkdir(parents=True, exist_ok=True)
    segs = ",".join([f"0-{LOOP_A}"] + [f"{LOOP_A}-{LOOP_B}"] * k + ([f"{LOOP_A}-{LOOP_A + PHRASE * m:.2f}"] if m else []) + [f"{LOOP_B}-{END_B}"])
    sh([sys.executable, str(V / "music_tools.py"), "splice", str(MUSIC), str(mdir / "music.wav"), "--segments", segs])
    sh([sys.executable, str(V / "music_tools.py"), "analyze", str(mdir / "music.wav"), "--out", str(mdir / "analysis.json")])
    script = {"duration": duration, "voice": VOICE, "model": TTS_MODEL, "settings": TTS_SETTINGS, "lines": lines, "sfx": [],
              "scenes": [{"id": "s_" + l["id"], "start": 0 if i == 0 else max(0, round(l["at"] - 0.5, 3))} for i, l in enumerate(lines)],
              "music": {"file": "audio/music/music.wav", "gain_db": -8, "duck": 0.72, "analysis": "audio/music/analysis.json"}}
    (work / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1))
    (work / "reel").mkdir(exist_ok=True)
    sh([sys.executable, str(V / "timeline.py"), str(work / "script.json"), "--music-analysis", str(mdir / "analysis.json")], cwd=work)
    print(f"   🎵 비트 4마디×{n4} · 영상 {duration:.1f}초 · 마지막 인사 끝 {prev:.1f}초")


# ─── 5. 편집 계획(클립 프레임) ───────────────────────────────
def pixabay_key():
    k = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not k:
        f = Path.home() / ".config/pixabay/api-key"
        k = f.read_text().strip() if f.exists() else ""
    if not k:
        raise SystemExit("PIXABAY_API_KEY 가 없다")
    return k


def fetch_clip(cid, cache):
    f = cache / f"{cid}.mp4"
    if f.exists() and f.stat().st_size > 10000:
        return f
    cache.mkdir(parents=True, exist_ok=True)
    q = urllib.parse.urlencode({"key": pixabay_key(), "id": cid})
    hit = json.loads(sh(["curl", "-s", "-m", "30", f"https://pixabay.com/api/videos/?{q}"]))["hits"][0]
    url = hit["videos"]["large"]["url"] or hit["videos"]["medium"]["url"]
    sh(["curl", "-s", "-L", "-m", "300", "-o", str(f), url])
    return f


def probe(f):
    pr = json.loads(sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-show_entries", "format=duration", "-of", "json", str(f)]))
    n, d = pr["streams"][0]["r_frame_rate"].split("/")
    return int(n) / int(d), float(pr["format"]["duration"])


def yavg(f, ss, dur):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.2f}", "-t", f"{max(0.5, dur):.2f}", "-i", str(f), "-vf",
                          "fps=2,scale=320:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
                         capture_output=True, text=True).stdout
    v = [float(x) for x in re.findall(r"YAVG=([\d.]+)", out)]
    return sum(v) / len(v) if v else 90.0


def plan(date, dg, sc, clips, work):
    TL = json.loads((work / "timeline.json").read_text())
    beats = json.loads((work / "audio/music/analysis.json").read_text())["beats"]
    snap = lambda t: min(beats, key=lambda b: abs(b - t))
    vo = {v["id"]: v for v in TL["vo"]}; order = [v["id"] for v in TL["vo"]]
    by = {c["id"]: c for c in clips}
    cat = lambda name: [c["id"] for c in clips if c["cat"] == name]
    cache = Path(os.environ.get("REEL_CLIP_CACHE", Path.home() / ".cache/trenddream-reel/clips"))
    arts = {f"a{a['num']}": a for a in sc["articles"]}
    dga = {f"a{a['num']}": a for a in dg["articles"]}
    src_dir = work / "assets/src"; src_dir.mkdir(parents=True, exist_ok=True)
    for a in dg["articles"]:
        if a.get("thumb") and (REPO / date / a["thumb"]).exists():
            shutil.copy(REPO / date / a["thumb"], src_dir / a["thumb"])
    seq = work / "assets/seq"
    shutil.rmtree(seq, ignore_errors=True); seq.mkdir(parents=True)
    needed = set(cat("open")[:1] + cat("transit")[:1] + cat("ending")[:2])
    for a in sc["articles"]:
        needed.update(a["clips"])
    with ThreadPoolExecutor(4) as ex:
        paths = dict(zip(needed, ex.map(lambda i: fetch_clip(i, cache), needed)))
    cuts = {sid: (0.0 if sid == "intro" else snap(vo[sid]["words"][0][1] - 0.4)) for sid in order}
    segs, shots, subs, jobs = [], [], [], []

    def add(sid, name, cid, a, b, ss=None):
        f = paths[cid]; fps, dur_src = probe(f); dur = b - a; nf = math.ceil(dur * FPS) + 2
        speed = 0.5 if fps >= 48 else 1.0; need = dur * speed
        if need > dur_src - 0.4:
            speed = (dur_src - 0.4) / dur; need = dur * speed
        ss = by[cid].get("ss", 1.0) if ss is None else ss
        ss = max(0.0, min(ss, dur_src - need - 0.2))
        y = yavg(f, ss, need); bright = max(-0.12, min(0.06, (88 - y) / 255 * 0.85))
        d = seq / name; d.mkdir()
        vf = f"setpts=PTS/{speed:.4f},fps={FPS},scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,eq=brightness={bright:.3f},{GRADE}"
        jobs.append(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.2f}", "-i", str(f), "-vf", vf, "-frames:v", str(nf), "-q:v", "3", str(d / "%05d.jpg")])
        shots.append({"seg": sid, "a": round(a, 3), "b": round(b, 3), "kind": "seq", "dir": f"../assets/seq/{name}/", "n": nf, "credit": cid})

    title_end = 5.2
    for k, sid in enumerate(order):
        s0 = cuts[sid]; s1 = cuts[order[k + 1]] if k + 1 < len(order) else TL["duration"]
        seg = {"id": sid, "start": round(s0, 3), "end": round(s1, 3)}
        if sid == "intro":
            h0 = snap(TL["cues"]["hook"] - 0.3); seg["hook"] = round(h0, 3)
            add(sid, "intro_0", cat("open")[0], s0, h0, 3.0)
            mont = [a["clips"][0] for a in sc["articles"]] + [a["clips"][1] for a in sc["articles"]]
            t, j = h0, 0
            while t < s1 - 0.05:
                b = min(s1, t + 0.8); add(sid, f"intro_m{j}", mont[j % len(mont)], t, b, 4.0 + (j // len(mont)) * 2); t = b; j += 1
        elif sid in ("branch", "outro"):
            ids = cat("transit")[:1] if sid == "branch" else cat("ending")[:2]
            bounds = [s0] + [snap(s0 + (s1 - s0) * j / len(ids)) for j in range(1, len(ids))] + [s1]
            for j, cid in enumerate(ids):
                add(sid, f"{sid}_{j}", cid, bounds[j], bounds[j + 1])
        else:
            a, g = arts[sid], dga[sid]
            src = urllib.parse.urlparse(g.get("link", "")).netloc.replace("www.", "")
            seg.update({"num": a["num"], "src": src, "head": a["head"], "thumb": g.get("thumb") or ""})
            K = TL["cues"].get(f"k{a['num']}")
            if a["key"] and K and K >= s0 + title_end + 0.2:
                seg.update({"key": a["key"], "cap": a["cap"], "K": round(K, 3)})
            if seg["thumb"]:
                lo, dur = s0 + title_end + 0.3, 4.2
                kw = (seg["K"] - 0.4, min(seg["K"] + 3.6, s1)) if "K" in seg else None
                e0 = max(lo, s0 + (s1 - s0) * 0.55)
                if kw and e0 < kw[1] and e0 + dur > kw[0]:
                    e0 = kw[1] + 0.1 if kw[1] + 0.1 + dur <= s1 - 0.3 else lo
                    if e0 == lo and kw[0] - 0.1 - lo >= 3.0:
                        dur = kw[0] - 0.1 - lo
                if kw and e0 < kw[1] and e0 + dur > kw[0]:
                    for x in ("K", "key", "cap"):
                        seg.pop(x, None)
                    e0, dur = max(lo, s0 + (s1 - s0) * 0.55), 4.2
                if e0 + 2.5 <= s1 - 0.3:
                    seg["ev"] = [round(e0, 3), round(min(e0 + dur, s1 - 0.3), 3)]
                else:
                    seg["thumb"] = ""
            ids = a["clips"]
            bounds = [s0] + [snap(s0 + (s1 - s0) * j / len(ids)) for j in range(1, len(ids))] + [s1]
            for j, cid in enumerate(ids):
                add(sid, f"{sid}_{j}", cid, bounds[j], bounds[j + 1])
            subs += subtitles(vo[sid], next(l for l in json.loads((work / "script.json").read_text())["lines"] if l["id"] == sid))
        segs.append(seg)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(sh, jobs))
    d = datetime.date.fromisoformat(date)
    meta = {"dateLabel": f"{d.year}. {d.month}. {d.day}. {WEEK[d.weekday()]}", "shortLabel": f"{d.month}.{d.day} {WEEK[d.weekday()][0]}",
            "hookLines": sc["hook"]["lines"]}
    (work / "reel/plan.js").write_text("window.PLAN = " + json.dumps({"segs": segs, "shots": shots, "subs": subs, "meta": meta}, ensure_ascii=False) + ";\n")
    credits = sorted({s["credit"] for s in shots})
    return {"segs": len(segs), "shots": len(shots), "subs": len(subs), "clips": credits}


def subtitles(v, line):
    """절(쉼표·마침표) 단위 자막. 27자가 넘는 절은 반으로 나눈다."""
    words = v["words"]
    tc = re.split(r"(?<=[,.])\s+", v["text"].strip()); scl = re.split(r"(?<=[,.])\s+", line["tts"].strip())
    if len(tc) != len(scl):                       # 쉼표 수가 다르면 문장 단위로만 맞춘다
        tc = re.split(r"(?<=\.)\s+", v["text"].strip()); scl = re.split(r"(?<=\.)\s+", line["tts"].strip())
        if len(tc) != len(scl):
            return []
    AUX = ("두", "주", "보", "놓", "있", "버", "싶", "줬", "뒀")
    w, chunks = 0, []
    for t_cl, s_cl in zip(tc, scl):
        nw = len(s_cl.split()); t0 = words[min(w, len(words) - 1)][1]; t1 = words[min(w + nw, len(words)) - 1][2]; w += nw
        t_cl = t_cl.rstrip(".")
        if len(t_cl) > 27:
            ws = t_cl.split(); best = None
            for c2 in range(1, len(ws)):
                l1, l2 = len(" ".join(ws[:c2])), len(" ".join(ws[c2:]))
                sc2 = abs(l1 - l2) + (9 if len(ws[c2]) == 1 else 0) + (9 if len(ws[c2 - 1]) == 1 else 0) \
                    + (4 if ws[c2 - 1].endswith("의") else 0) + (14 if ws[c2].startswith(AUX) and ws[c2 - 1].endswith(("어", "아", "고", "해")) else 0)
                if best is None or sc2 < best[0]:
                    best = (sc2, c2)
            p1, p2 = " ".join(ws[:best[1]]), " ".join(ws[best[1]:]); tm = t0 + (t1 - t0) * len(p1) / len(t_cl)
            chunks += [[t0, tm, p1], [tm, t1, p2]]
        else:
            chunks.append([t0, t1, t_cl])
    out = []
    for i, (t0, t1, tx) in enumerate(chunks):
        nxt = chunks[i + 1][0] if i + 1 < len(chunks) else t1 + 0.6
        out.append({"t0": round(t0 - 0.08, 3), "t1": round(min(nxt - 0.04, t1 + 0.45), 3), "text": tx})
    return out


# ─── 6. 렌더·믹스 ────────────────────────────────────────────
def render(work):
    if not (V / "node_modules/playwright-core").exists():
        sh(["npm", "ci", "--no-audit", "--no-fund"], cwd=V)
    sub = os.environ.get("REEL_SUB", "2")
    out = work / "out"; out.mkdir(exist_ok=True)
    print(sh(["node", str(V / "render.mjs"), "--dir", str(work / "reel"), "--out", str(out / "video.mp4"), "--sub", sub, "--format", "png"]).strip().splitlines()[-1])
    print(sh([sys.executable, str(V / "mix.py"), str(work / "timeline.json"), "--tp", "-3.0"]).strip().splitlines()[-2])
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(out / "video.mp4"), "-i", str(work / "audio/mix.wav"), "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
        "-color_trc", "bt709", "-color_range", "tv", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out / "reel.mp4")])
    return out / "reel.mp4"


def prepare_reel_dir(work):
    r = work / "reel"; r.mkdir(parents=True, exist_ok=True)
    for f in ("index.html", "engine.js", "fx.js", "scenes.js"):
        shutil.copy(ROOT / "template" / f, r / f)
    shutil.copytree(ROOT / "template/fonts", r / "fonts", dirs_exist_ok=True)


STAGES = ["script", "voice", "place", "plan", "render"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--work")
    ap.add_argument("--from", dest="start", choices=STAGES, default="script")
    a = ap.parse_args()
    work = Path(a.work or ROOT / "_work" / a.date).resolve(); work.mkdir(parents=True, exist_ok=True)
    run = lambda st: STAGES.index(st) >= STAGES.index(a.start)
    dg = load_digest(a.date)
    clips = json.loads((ROOT / "clips.json").read_text())["clips"]
    t0 = datetime.datetime.now()
    sfile = work / "script_llm.json"
    if run("script") or not sfile.exists():
        print("✍️  대본 쓰는 중…"); sfile.write_text(json.dumps(write_script(dg, clips, a.date), ensure_ascii=False, indent=1))
    sc = json.loads(sfile.read_text())
    paras = paragraphs(sc, a.date)
    if run("voice") or not (work / "audio/vo/report.json").exists():
        print("🎙  나레이션 생성 중…"); take = voice(paras, work); split_take(take, paras, work)
    rep = json.loads((work / "audio/vo/report.json").read_text())
    prepare_reel_dir(work)
    if run("place") or not (work / "timeline.json").exists():
        print("🎵 배치 중…"); place(paras, rep, sc, work)
    if run("plan") or not (work / "reel/plan.js").exists():
        print("🎞  클립 준비 중…"); info = plan(a.date, dg, sc, clips, work); print(f"   {info}")
    print("🎬 렌더 중…"); mp4 = render(work)
    dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)]))
    meta = {"date": a.date, "file": str(mp4), "duration": round(dur, 2), "size": mp4.stat().st_size,
            "built_at": datetime.datetime.now().isoformat(timespec="seconds"), "elapsed_sec": int((datetime.datetime.now() - t0).total_seconds()),
            "articles": [x["num"] for x in sc["articles"]], "titles_hash": __import__("hashlib").sha1(json.dumps([x.get("title") for x in dg["articles"]], ensure_ascii=False).encode()).hexdigest()[:12]}
    (work / "out/meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"✅ {mp4} ({dur:.1f}초, {mp4.stat().st_size / 1048576:.1f}MB, {meta['elapsed_sec']}초 걸림)")


if __name__ == "__main__":
    main()
