import re, glob, sys

CSS_START = '/*GNB-CSS-START*/'
CSS_END = '/*GNB-CSS-END*/'
HTML_START = '<!--GNB-HTML-START-->'
HTML_END = '<!--GNB-HTML-END-->'
JS_START = '<!--GNB-JS-START-->'
JS_END = '<!--GNB-JS-END-->'

GNB_CSS_BODY = (
    "html{scroll-padding-top:var(--gnb-h,56px);scroll-behavior:smooth;}"
    "body::before{content:'';position:fixed;top:0;left:0;right:0;height:env(safe-area-inset-top,0px);background-color:var(--surface);z-index:200;pointer-events:none;}"
    ".gnb{position:sticky;top:0;z-index:100;background:var(--gnb-bg,rgba(255,255,255,0.85));backdrop-filter:saturate(160%) blur(12px);-webkit-backdrop-filter:saturate(160%) blur(12px);border-bottom:1px solid var(--line);}"
    ".gnb-inner{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 20px;max-width:1320px;margin:0 auto;}"
    ".gnb-brand{display:inline-flex;align-items:baseline;gap:8px;font-size:16px;font-weight:700;color:var(--text);text-decoration:none;letter-spacing:-0.02em;white-space:nowrap;cursor:pointer;}"
    ".gnb-date{font-weight:500;color:var(--text4);font-variant-numeric:tabular-nums;letter-spacing:0;font-size:14px;}"
    ".gnb-toc-btn{display:inline-flex;align-items:center;gap:9px;padding:7px 8px 7px 14px;background:var(--surface);border:1px solid var(--line);border-radius:999px;cursor:pointer;font-size:12px;font-weight:600;color:var(--text2);font-family:inherit;line-height:1;transition:all 0.18s;}"
    ".gnb-toc-btn:hover{border-color:var(--label-border,var(--text4));color:var(--text);}"
    ".gnb-toc-btn[aria-expanded='true']{background:var(--page);border-color:var(--text4);color:var(--text);}"
    ".gnb-toc-progress{display:inline-flex;align-items:center;padding:3px 8px;background:var(--page);border-radius:999px;color:var(--text4);font-variant-numeric:tabular-nums;font-size:11px;font-weight:700;letter-spacing:0.02em;transition:all 0.18s;}"
    ".gnb-toc-btn:hover .gnb-toc-progress,.gnb-toc-btn[aria-expanded='true'] .gnb-toc-progress{background:var(--surface);color:var(--text2);}"
    ".gnb-progress-track{position:absolute;left:0;right:0;bottom:-1px;height:2px;background:transparent;pointer-events:none;}"
    ".gnb-progress-fill{height:100%;background:var(--text);width:0;transition:width 0.1s linear;}"
    "body.toc-open{overflow:hidden;}"
    ".toc-panel{position:fixed;inset:0;z-index:300;visibility:hidden;pointer-events:none;}"
    ".toc-panel.open{visibility:visible;pointer-events:auto;}"
    ".toc-overlay{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);opacity:0;transition:opacity 0.25s ease;}"
    ".toc-panel.open .toc-overlay{opacity:1;}"
    ".toc-drawer{position:absolute;top:0;left:0;right:0;bottom:0;background:var(--surface);transform:translateY(100%);transition:transform 0.38s cubic-bezier(0.32,0.72,0,1);display:flex;flex-direction:column;}"
    ".toc-panel.open .toc-drawer{transform:translateY(0);}"
    ".toc-header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 14px;flex-shrink:0;}"
    ".toc-title{font-size:18px;font-weight:700;letter-spacing:-0.01em;color:var(--text);}"
    ".toc-close{background:transparent;border:0;font-size:28px;cursor:pointer;color:var(--text2);padding:0 6px;line-height:1;font-family:inherit;}"
    ".toc-close:hover{color:var(--text);}"
    ".toc-list{list-style:none;padding:4px 12px 32px;margin:0;overflow-y:auto;flex:1;-webkit-overflow-scrolling:touch;}"
    ".toc-list li{margin:0;}"
    ".toc-item{display:flex;gap:14px;align-items:flex-start;padding:14px 14px;text-decoration:none;color:inherit;border-radius:10px;opacity:0;transform:translateY(20px);transition:opacity 0.4s ease,transform 0.5s cubic-bezier(0.32,0.72,0,1),background-color 0.18s,color 0.18s;}"
    ".toc-panel.open .toc-item{opacity:1;transform:translateY(0);}"
    ".toc-item:hover{background:var(--page);}"
    ".toc-item.active{background:var(--page);}"
    ".toc-num{font-size:11px;font-weight:700;color:var(--text5);letter-spacing:0.08em;padding-top:4px;flex-shrink:0;min-width:24px;font-variant-numeric:tabular-nums;}"
    ".toc-text{font-size:16px;line-height:1.5;color:var(--text);word-break:keep-all;font-weight:500;}"
    ".toc-item.active .toc-text{font-weight:700;}"
    # article-label: editorial kicker style (just numbering, no chip)
    ".article-label{display:block;margin-bottom:10px;padding:0;background:transparent;border:0;border-radius:0;font-size:13px;font-weight:700;letter-spacing:0.04em;color:var(--text4);font-variant-numeric:tabular-nums;line-height:1;text-transform:none;}"
    ".link-box{padding:8px 12px;}"
    # agit-cta + back-to-top: 2-col flex with identical outline button design
    ".agit-cta{display:flex;gap:10px;margin:0 20px;border-top:1px solid var(--line);padding:20px 0 28px;text-align:left;}"
    ".back-to-top,.agit-cta-btn{flex:1;display:inline-flex;align-items:center;justify-content:center;width:auto;height:44px;padding:0 16px;background:transparent;color:var(--text2) !important;border:1px solid var(--line);border-radius:999px;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;text-decoration:none;letter-spacing:-0.01em;transition:border-color 0.18s,color 0.18s,background 0.18s;-webkit-tap-highlight-color:transparent;}"
    "@media (hover:hover){"
        ".back-to-top:hover,.agit-cta-btn:hover{opacity:1;border-color:var(--text2);color:var(--text) !important;background:var(--page);}"
    "}"
    ".back-to-top:active,.agit-cta-btn:active{background:var(--page);}"
    ".back-to-top:focus,.agit-cta-btn:focus{outline:none;}"
    ".back-to-top:focus-visible,.agit-cta-btn:focus-visible{outline:2px solid var(--text2);outline-offset:2px;}"
    # 768+: remove page frame and card border/radius (since .page wrapper is removed)
    "@media (min-width:768px){"
        "html,body{background:var(--surface);}"
        ".card{border:0;border-radius:0;}"
    "}"
    "@media (min-width:768px){"
        ".gnb-inner{padding:14px 32px;}"
        ".toc-drawer{left:auto;width:420px;max-width:92vw;transform:translateX(100%);border-left:1px solid var(--line);box-shadow:-12px 0 40px rgba(0,0,0,0.12);}"
        ".toc-panel.open .toc-drawer{transform:translateX(0);}"
        ".toc-item{transform:translateX(30px);}"
        ".toc-panel.open .toc-item{transform:translateX(0);}"
        ".toc-header{padding:22px 24px 16px;}"
        ".toc-title{font-size:20px;}"
        ".toc-list{padding:4px 16px 40px;}"
        ".agit-cta{margin:0 32px;padding:32px 0 32px;gap:12px;}"
        ".back-to-top,.agit-cta-btn{height:48px;font-size:14px;}"
    "}"
    "@media (min-width:1200px){.gnb-inner{padding:14px 40px;}.agit-cta{margin:0 40px;}}"
    "@media (min-width:1600px){.gnb-inner{max-width:1800px;}}"
)

GNB_HTML_BODY = (
    '<nav class="gnb"><div class="gnb-inner">'
    '<a href="#top" class="gnb-brand" data-gnb-top>트렌드림 <span class="gnb-date"></span></a>'
    '<button class="gnb-toc-btn" type="button" aria-expanded="false" aria-controls="toc-panel">'
    '<span>목차</span>'
    '<span class="gnb-toc-progress"><span class="cur">1</span>/<span class="tot">0</span></span>'
    '</button>'
    '</div><div class="gnb-progress-track"><div class="gnb-progress-fill"></div></div></nav>'
    '<aside id="toc-panel" class="toc-panel" aria-hidden="true">'
    '<div class="toc-overlay"></div>'
    '<div class="toc-drawer">'
    '<div class="toc-header"><span class="toc-title">목차</span><button type="button" class="toc-close" aria-label="목차 닫기">×</button></div>'
    '<ol class="toc-list"></ol>'
    '</div></aside>'
)

GNB_JS_BODY = '''<script>(function(){
var media=window.matchMedia('(prefers-color-scheme: dark)');
function syncThemeColor(){
var color=media.matches?'#1a1a1a':'#ffffff';
var olds=document.querySelectorAll('meta[name="theme-color"]');
for(var i=0;i<olds.length;i++)olds[i].parentNode.removeChild(olds[i]);
var meta=document.createElement('meta');
meta.setAttribute('name','theme-color');
meta.setAttribute('content',color);
document.head.appendChild(meta);
}
syncThemeColor();
if(media.addEventListener)media.addEventListener('change',syncThemeColor);
else if(media.addListener)media.addListener(syncThemeColor);
var arts=document.querySelectorAll('.article-item');
if(!arts.length)return;
var gnb=document.querySelector('.gnb');
var tocList=document.querySelector('.toc-list');
var tocBtn=document.querySelector('.gnb-toc-btn');
var tocPanel=document.getElementById('toc-panel');
var tocClose=document.querySelector('.toc-close');
var tocOverlay=document.querySelector('.toc-overlay');
var fill=document.querySelector('.gnb-progress-fill');
var curEl=document.querySelector('.gnb-toc-progress .cur');
var totEl=document.querySelector('.gnb-toc-progress .tot');
var brand=document.querySelector('[data-gnb-top]');
var dateEl=document.querySelector('.gnb-date');
var DAYS=['일','월','화','수','목','금','토'];
var pm=location.pathname.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
if(pm&&dateEl){
var y=parseInt(pm[1],10),mo=parseInt(pm[2],10),d=parseInt(pm[3],10);
var dow=DAYS[new Date(y,mo-1,d).getDay()];
dateEl.textContent=(y%100)+'. '+mo+'. '+d+' ('+dow+')';
}
function updateGnbH(){if(gnb)document.documentElement.style.setProperty('--gnb-h',gnb.offsetHeight+'px');}
updateGnbH();
window.addEventListener('resize',updateGnbH);
arts.forEach(function(art,i){
art.id='article-'+(i+1);
var num='#'+(i+1);
var lbl=art.querySelector('.article-label');
if(lbl)lbl.textContent=num;
var t=art.querySelector('.article-title');
var title=t?t.textContent.trim():'Article '+(i+1);
var li=document.createElement('li');
var a=document.createElement('a');
a.href='#article-'+(i+1);a.className='toc-item';
var ns=document.createElement('span');ns.className='toc-num';ns.textContent=num;
var ts=document.createElement('span');ts.className='toc-text';ts.textContent=title;
a.appendChild(ns);a.appendChild(ts);li.appendChild(a);tocList.appendChild(li);
});
totEl.textContent=arts.length;
var items=document.querySelectorAll('.toc-item');
function setOpen(o){
if(o){
items.forEach(function(it,i){var d=(0.06+i*0.045)+'s';it.style.transitionDelay=d+','+d+',0s,0s';});
}else{
items.forEach(function(it){it.style.transitionDelay='0s';});
}
tocPanel.classList.toggle('open',o);
tocPanel.setAttribute('aria-hidden',!o);
tocBtn.setAttribute('aria-expanded',o);
document.body.classList.toggle('toc-open',o);
}
tocBtn.addEventListener('click',function(){setOpen(!tocPanel.classList.contains('open'));tocBtn.blur();});
if(tocClose)tocClose.addEventListener('click',function(){setOpen(false);});
if(tocOverlay)tocOverlay.addEventListener('click',function(){setOpen(false);});
tocPanel.addEventListener('click',function(e){if(e.target.closest('a.toc-item'))setOpen(false);});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&tocPanel.classList.contains('open'))setOpen(false);});
if(brand){brand.addEventListener('click',function(e){e.preventDefault();window.scrollTo({top:0,behavior:'smooth'});brand.blur();});}
function setActive(idx){
curEl.textContent=idx+1;
items.forEach(function(it,i){it.classList.toggle('active',i===idx);});
}
if('IntersectionObserver' in window){
var io=new IntersectionObserver(function(entries){
var vis=entries.filter(function(e){return e.isIntersecting;});
if(vis.length){
vis.sort(function(a,b){return a.target.getBoundingClientRect().top-b.target.getBoundingClientRect().top;});
var idx=Array.prototype.indexOf.call(arts,vis[0].target);
setActive(idx);
}
},{rootMargin:'-30% 0px -55% 0px',threshold:0});
arts.forEach(function(a){io.observe(a);});
}
function updateProgress(){
var d=document.documentElement;
var total=d.scrollHeight-window.innerHeight;
var cur=window.scrollY||d.scrollTop;
var pct=total>0?Math.min(100,(cur/total)*100):0;
fill.style.width=pct+'%';
}
window.addEventListener('scroll',updateProgress,{passive:true});
window.addEventListener('resize',updateProgress);
updateProgress();
var cta=document.querySelector('.agit-cta');
if(cta){
var bt=document.createElement('button');
bt.type='button';
bt.className='back-to-top';
bt.textContent='맨 위로';
bt.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});bt.blur();});
cta.insertBefore(bt,cta.firstChild);
var agitBtn=cta.querySelector('.agit-cta-btn');
if(agitBtn)agitBtn.addEventListener('click',function(){agitBtn.blur();});
}
})();</script>'''

LIGHT_VARS = {
    '--gnb-bg': 'rgba(255,255,255,0.85)',
    '--label-bg': '#f5f5f5',
    '--label-text': '#999',
    '--label-border': 'transparent',
}
DARK_VARS = {
    '--gnb-bg': 'rgba(26,26,26,0.85)',
    '--label-bg': '#2a2a2a',
    '--label-text': '#777',
    '--label-border': 'transparent',
}

def upsert_vars(root_block, vars_dict):
    block = root_block
    for k, v in vars_dict.items():
        block = re.sub(re.escape(k) + r'\s*:\s*[^;]+;\s*', '', block)
    decl = ' '.join(f'{k}:{v};' for k, v in vars_dict.items())
    block = re.sub(r'(\s*\}\s*)$', ' ' + decl + r'\1', block, count=1)
    return block

def remove_header_element(content):
    new_content, n = re.subn(r'<header class="header">.*?</header>\s*', '', content, count=1, flags=re.DOTALL)
    if n: return new_content
    new_content, n = re.subn(
        r'<div class="header">\s*<h1[^>]*>.*?</h1>\s*<div class="header-meta">.*?</div>\s*</div>\s*',
        '', content, count=1, flags=re.DOTALL
    )
    return new_content

def unwrap_page_div(content):
    if '<div class="page">' not in content:
        return content
    new_content, n = re.subn(
        r'<div class="page">(.*?)</div>(\s*</body>)',
        r'\1\2', content, count=1, flags=re.DOTALL
    )
    return new_content

def update_agit_label(content):
    return content.replace('트렌드림 아지트로 돌아가기', '트렌드림 아지트')

def ensure_viewport_fit_cover(content):
    def repl(m):
        attrs = m.group(0)
        cm = re.search(r'content\s*=\s*"([^"]*)"', attrs)
        if not cm:
            return attrs
        val = cm.group(1)
        if 'viewport-fit' in val:
            return attrs
        new_val = val.rstrip().rstrip(',') + ', viewport-fit=cover'
        return attrs.replace(cm.group(0), f'content="{new_val}"')
    return re.sub(r'<meta[^>]*name\s*=\s*"viewport"[^>]*>', repl, content, count=1)

def strip_theme_color(content):
    return re.sub(r'<meta[^>]*name\s*=\s*"theme-color"[^>]*>', '', content)

THEME_COLOR_TAGS = (
    '<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">'
    '<meta name="theme-color" content="#1a1a1a" media="(prefers-color-scheme: dark)">'
)

def ensure_theme_color(content):
    content = strip_theme_color(content)
    vm = re.search(r'<meta[^>]*name\s*=\s*"viewport"[^>]*>', content)
    if not vm:
        return content
    insert_at = vm.end()
    return content[:insert_at] + THEME_COLOR_TAGS + content[insert_at:]

def strip_existing_gnb(content):
    content = re.sub(re.escape(CSS_START) + r'.*?' + re.escape(CSS_END), '', content, flags=re.DOTALL)
    content = re.sub(re.escape(HTML_START) + r'.*?' + re.escape(HTML_END), '', content, flags=re.DOTALL)
    content = re.sub(re.escape(JS_START) + r'.*?' + re.escape(JS_END), '', content, flags=re.DOTALL)
    # V3 legacy
    content = re.sub(r'<!--GNB-V3-INJECTED-->.*?</aside>', '', content, flags=re.DOTALL)
    content = re.sub(
        r'<script>\(function\(\)\{\s*var arts=document\.querySelectorAll[\s\S]*?\}\)\(\);</script>(?=\s*</body>)',
        '', content
    )
    content = re.sub(
        r'html\{scroll-padding-top:64px;scroll-behavior:smooth;\}\.gnb\{[\s\S]*?@media \(min-width:1600px\)\{\.gnb-inner\{max-width:1800px;\}\}',
        '', content
    )
    # Strip vars from :root (will be re-inserted with new values)
    for v in ('--gnb-bg', '--label-bg', '--label-text', '--label-border'):
        content = re.sub(r'\s*' + re.escape(v) + r'\s*:[^;]+;', '', content)
    return content

def process_file(path):
    with open(path) as f:
        content = f.read()
    original = content

    content = strip_existing_gnb(content)
    content = remove_header_element(content)
    content = unwrap_page_div(content)
    content = update_agit_label(content)
    content = ensure_viewport_fit_cover(content)
    content = ensure_theme_color(content)

    roots = list(re.finditer(r':root\s*\{[^}]+\}', content))
    if roots:
        if len(roots) >= 2:
            m = roots[1]
            content = content[:m.start()] + upsert_vars(m.group(0), DARK_VARS) + content[m.end():]
        roots = list(re.finditer(r':root\s*\{[^}]+\}', content))
        m = roots[0]
        content = content[:m.start()] + upsert_vars(m.group(0), LIGHT_VARS) + content[m.end():]

    if '</style>' not in content:
        return False, "no </style>"
    content = content.replace('</style>', CSS_START + GNB_CSS_BODY + CSS_END + '</style>', 1)

    body_open_match = re.search(r'<body[^>]*>', content)
    if not body_open_match:
        return False, "no <body>"
    insert_at = body_open_match.end()
    content = content[:insert_at] + HTML_START + GNB_HTML_BODY + HTML_END + content[insert_at:]

    if '</body>' not in content:
        return False, "no </body>"
    content = content.replace('</body>', JS_START + GNB_JS_BODY + JS_END + '</body>', 1)

    if content == original:
        return False, "no change"
    with open(path, 'w') as f:
        f.write(content)
    return True, "ok"

if __name__ == '__main__':
    paths = sorted(glob.glob('index.html') + glob.glob('2026-*/index.html') + glob.glob('test/index.html'))
    if len(sys.argv) > 1:
        paths = sys.argv[1:]
    print(f"Processing {len(paths)} files...")
    fail = 0
    for p in paths:
        ok, msg = process_file(p)
        status = "OK" if ok else "SKIP"
        print(f"  [{status}] {p}: {msg}")
        if not ok and msg not in ("already injected", "no change"):
            fail += 1
    print(f"Done. Failures: {fail}/{len(paths)}")
