#!/usr/bin/env python3
"""요약 영상 아지트 업로드 잡 (맥 launchd, 5분마다).

깃헙 액션(reel.yml)이 만든 그날 영상(아티팩트 reel-YYYY-MM-DD)을 받아, 로그인된 크롬의 아지트 탭 안에서
secure_upload 로 올리고(발행은 하지 않는다) 받은 영상 ID 를 레포 reel/ready/<날짜>-<그룹>.json 에 기록한다.
10시 agit-post.yml 이 그 ID 를 웹훅 본문 {VIDEO:<id>} 로 넣어 다이제스트 안에 플레이어를 붙인다.

조건이 안 맞으면 조용히 끝내고 다음 5분에 다시 본다: 주말·시간 창 밖(07:30~11:05), 영상 아직 없음,
다이제스트가 바뀌어 영상이 옛 내용, 크롬에 아지트 탭 없음·사내망 밖(ip_blocked)·로그인 만료.
문제는 하루 한 번만 맥 알림으로 알린다.

수동 실행: python3 reel/mac/reel_upload.py [--date 2026-11-27] [--group 300073740] [--force]
"""
import argparse, base64, datetime, hashlib, http.server, json, os, re, subprocess, sys, tempfile, threading, time
from pathlib import Path

REPO = "Leche/trend-articles"
GROUP_REAL = "300044281"                   # 트렌드림 그룹(본 웹훅이 발행하는 곳)
STATE = Path.home() / "Library/Application Support/trenddream-reel"
KST = datetime.timezone(datetime.timedelta(hours=9))
ENV = {**os.environ, "GH_HOST": "github.com", "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")}


def log(*a):
    print(datetime.datetime.now(KST).strftime("%m-%d %H:%M:%S"), *a, flush=True)


def gh(*args, raw=False):
    r = subprocess.run(["gh", *args], capture_output=True, env=ENV)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} 실패: {r.stderr.decode()[-300:]}")
    return r.stdout if raw else r.stdout.decode()


def notify_once(key, msg):
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / "notified.json"
    seen = json.loads(f.read_text()) if f.exists() else {}
    k = f"{datetime.date.today()}:{key}"
    if k in seen:
        return
    seen[k] = True; f.write_text(json.dumps(seen))
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "트렌드림 요약 영상"'], capture_output=True)
    log("알림:", msg)


# ─── 크롬 아지트 탭 ──────────────────────────────────────────
def _osa(script, timeout=90):
    try:
        r = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode:
        log("osascript 오류:", r.stderr.strip()[-200:])
    return r.stdout.strip() if r.returncode == 0 else None


def _q(code):
    return '"' + code.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_tab():
    """사내망 아지트 탭 중 깨어 있는 것(자바스크립트가 5초 안에 응답)을 찾아 'window id,tab id' 로 돌려준다.
    크롬 메모리 절약으로 잠든 탭은 응답하지 않으므로 건너뛴다. 찾은 탭은 기억해 두고 다음에 먼저 쓴다."""
    f = STATE / "tab.txt"
    if f.exists():
        wid, tid = f.read_text().split(",")
        probe = f'''tell application "Google Chrome"
  try
    with timeout of 5 seconds
      set t to tab id {tid} of window id {wid}
      if (URL of t) starts with "https://kakao.agit.in/" and (URL of t) does not contain "ip_blocked" then return (execute t javascript "1")
    end timeout
  end try
end tell
return ""'''
        if _osa(probe, 15) == "1":
            return wid, tid
    scan = '''tell application "Google Chrome"
  if not running then return ""
  repeat with w in windows
    set ts to (tabs of w whose URL starts with "https://kakao.agit.in/")
    repeat with i from (count of ts) to 1 by -1
      set t to item i of ts
      if (URL of t) does not contain "ip_blocked" then
        try
          with timeout of 5 seconds
            execute t javascript "1"
            return ((id of w) as text) & "," & ((id of t) as text)
          end timeout
        end try
      end if
    end repeat
  end repeat
end tell
return ""'''
    out = _osa(scan, 240)
    if not out:
        return None
    STATE.mkdir(parents=True, exist_ok=True); f.write_text(out)
    return tuple(out.split(","))


def chrome_js(code, tab=None):
    """깨어 있는 아지트 탭에서 자바스크립트를 실행한다. 탭이 없으면 None."""
    tab = tab or find_tab()
    if not tab:
        return None
    wid, tid = tab
    script = f'''tell application "Google Chrome"
  with timeout of 20 seconds
    return (execute (tab id {tid} of window id {wid}) javascript {_q(code)})
  end timeout
end tell'''
    return _osa(script, 40)


def serve(path):
    """영상 파일 하나를 127.0.0.1 에서만 내보낸다(아지트 탭이 fetch 로 읽게). 포트를 돌려준다."""
    data = Path(path).read_bytes()

    class H(http.server.BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "https://kakao.agit.in")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")

        def do_OPTIONS(self):
            self.send_response(204); self._cors(); self.end_headers()

        def do_GET(self):
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "video/mp4"); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def upload(mp4, group):
    srv = serve(mp4); port = srv.server_address[1]
    try:
        start = ("(function(){window.__reelUp=null;"
                 f"fetch('http://127.0.0.1:{port}/reel.mp4').then(r=>r.blob()).then(b=>{{const f=new FormData();"
                 "f.append('files[]',new File([b],'trenddream-reel.mp4',{type:'video/mp4'}));"
                 f"return fetch('/api/groups/{group}/wall/secure_upload',{{method:'POST',credentials:'include',"
                 "headers:{Authorization:'Bearer '+localStorage.getItem('u_token'),'X-Requested-With':'XMLHttpRequest',Accept:'application/json'},body:f})})"
                 ".then(async r=>{const t=await r.text();window.__reelUp=JSON.stringify({status:r.status,body:t.slice(0,1500)})})"
                 ".catch(e=>{window.__reelUp=JSON.stringify({status:-1,body:String(e)})});return 'started'})()")
        tab = find_tab()
        if not tab or chrome_js(start, tab) != "started":
            raise RuntimeError("크롬 탭에서 업로드를 시작하지 못했다")
        for _ in range(200):                         # 최대 10분
            time.sleep(3)
            v = chrome_js("window.__reelUp || ''", tab)
            if v:
                res = json.loads(v)
                if res["status"] != 200:
                    raise RuntimeError(f"업로드 실패 {res['status']}: {res['body'][:200]}")
                s = json.loads(res["body"])["stashes"][0]
                if s.get("format_type") != "video":
                    raise RuntimeError(f"영상으로 인식되지 않음: {s.get('format_type')}")
                return s["id"]
        raise RuntimeError("업로드가 10분 안에 끝나지 않았다")
    finally:
        srv.shutdown()


# ─── 영상·다이제스트 ─────────────────────────────────────────
def titles_hash(date):
    html = gh("api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/{date}/index.html")
    m = re.search(r'<script id="agit-digest-data" type="application/json">(.*?)</script>', html, re.S)
    dg = json.loads(m.group(1))
    return hashlib.sha1(json.dumps([x.get("title") for x in dg["articles"]], ensure_ascii=False).encode()).hexdigest()[:12]


def find_video(date, want_hash):
    """그날 성공한 reel.yml 실행 중 최신 다이제스트와 같은 내용으로 만든 영상(가장 최근)을 찾는다."""
    runs = json.loads(gh("run", "list", "-R", REPO, "-w", "reel.yml", "-L", "20", "--json", "databaseId,status,conclusion,createdAt"))
    cache = STATE / "artifacts"
    for r in runs:
        if r["status"] != "completed" or r["conclusion"] != "success":
            continue
        made = datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")).astimezone(KST).date()
        if made.isoformat() < (datetime.date.fromisoformat(date) - datetime.timedelta(days=1)).isoformat():
            break
        d = cache / str(r["databaseId"])
        if not (d / "meta.json").exists():
            d.mkdir(parents=True, exist_ok=True)
            try:
                gh("run", "download", str(r["databaseId"]), "-R", REPO, "-n", f"reel-{date}", "-D", str(d))
            except RuntimeError:
                continue                                    # 다른 날짜 실행
        meta = json.loads((d / "meta.json").read_text())
        if meta.get("date") == date and meta.get("titles_hash") == want_hash:
            return d / "reel.mp4", meta, r["databaseId"]
    return None


def write_ready(date, group, rec):
    path = f"reel/ready/{date}-{group}.json"
    sha = None
    try:
        sha = json.loads(gh("api", f"repos/{REPO}/contents/{path}"))["sha"]
    except RuntimeError:
        pass
    args = ["api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "-f", f"message=🎬 {date} 요약 영상 업로드 기록(그룹 {group})",
            "-f", "content=" + base64.b64encode(json.dumps(rec, ensure_ascii=False, indent=1).encode()).decode()]
    if sha:
        args += ["-f", f"sha={sha}"]
    gh(*args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--group", default=GROUP_REAL); ap.add_argument("--force", action="store_true")
    ap.add_argument("--check-chrome", action="store_true", help="크롬 아지트 탭 연결만 확인")
    a = ap.parse_args()
    if a.check_chrome:
        log("크롬 확인:", chrome_js("localStorage.getItem('u_token') ? 'login ok' : 'login no'") or "탭 없음"); return
    now = datetime.datetime.now(KST)
    date = a.date or now.date().isoformat()
    if not a.force and (now.weekday() >= 5 or not (datetime.time(7, 30) <= now.time() <= datetime.time(11, 5))):
        return
    STATE.mkdir(parents=True, exist_ok=True)
    done_f = STATE / "uploaded.json"
    done = json.loads(done_f.read_text()) if done_f.exists() else {}
    try:
        want = titles_hash(date)
    except Exception as e:
        log("다이제스트 없음:", e); return
    key = f"{date}-{a.group}"
    if done.get(key, {}).get("titles_hash") == want and not a.force:
        return                                              # 이미 올림
    found = find_video(date, want)
    if not found:
        log("아직 최신 영상 없음"); return
    mp4, meta, run_id = found
    tok = chrome_js("localStorage.getItem('u_token') ? 'yes' : 'no'")
    if tok is None:
        notify_once("tab", "크롬에 사내망 아지트 탭이 없어서 영상을 못 올렸어요. 아지트를 열어 두세요."); return
    if tok != "yes":
        notify_once("login", "아지트 로그인이 풀려 있어요. 크롬에서 아지트에 다시 로그인해 주세요."); return
    log(f"업로드 시작: {mp4} ({mp4.stat().st_size / 1048576:.1f}MB) → 그룹 {a.group}")
    vid = upload(mp4, a.group)
    rec = {"date": date, "group": a.group, "video_id": vid, "titles_hash": want, "run_id": run_id,
           "duration": meta.get("duration"), "uploaded_at": datetime.datetime.now(KST).isoformat(timespec="seconds")}
    write_ready(date, a.group, rec)
    done[key] = rec; done_f.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    log(f"완료: 영상 ID {vid} 기록")
    subprocess.run(["osascript", "-e", f'display notification "{date} 영상을 아지트에 올려 두었어요(ID {vid}). 10시 다이제스트에 들어가요." with title "트렌드림 요약 영상"'], capture_output=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("오류:", e)
        notify_once("error", f"영상 업로드 오류: {str(e)[:80]}")
        sys.exit(1)
