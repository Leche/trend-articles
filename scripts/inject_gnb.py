import re, glob, sys

CSS_START = '/*GNB-CSS-START*/'
CSS_END = '/*GNB-CSS-END*/'
HTML_START = '<!--GNB-HTML-START-->'
HTML_END = '<!--GNB-HTML-END-->'
JS_START = '<!--GNB-JS-START-->'
JS_END = '<!--GNB-JS-END-->'

GNB_CSS_BODY = (
    "html{scroll-padding-top:var(--gnb-h,55px);scroll-behavior:smooth;}"
    # Hide scrollbars while keeping scroll functional (mobile + desktop)
    "html,body,.toc-list{scrollbar-width:none;-ms-overflow-style:none;}"
    "html::-webkit-scrollbar,body::-webkit-scrollbar,.toc-list::-webkit-scrollbar{display:none;width:0;height:0;}"
    "body{padding-top:var(--gnb-h,55px);}"
    # GNB: solid translucent bg + 8px blur (Figma 6948:2157)
    ":root{--gnb-bg:rgba(255,255,255,0.32);--gnb-date-color:rgba(25,25,25,0.48);}"
    "@media (prefers-color-scheme:dark){:root{--gnb-bg:rgba(26,26,26,0.32);--gnb-date-color:rgba(232,232,232,0.48);}}"
    ".gnb{position:fixed;top:0;left:0;right:0;z-index:100;height:55px;background:var(--gnb-bg);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);pointer-events:none;}"
    ".gnb-inner{position:absolute;top:0;left:0;right:0;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px;pointer-events:auto;}"
    ".gnb-brand{display:flex;flex-direction:row;align-items:center;gap:6px;color:var(--text);text-decoration:none;white-space:nowrap;cursor:pointer;-webkit-tap-highlight-color:transparent;}"
    ".gnb-brand-name{font-family:'Pretendard',inherit;font-weight:700;font-size:18px;line-height:normal;}"
    ".gnb-date{font-family:'Pretendard',inherit;font-weight:600;font-size:14px;line-height:normal;color:var(--gnb-date-color);font-variant-numeric:tabular-nums;}"
    # TOC button: solid dark bg + white text (Figma 6948:2162)
    ".gnb-toc-btn{display:inline-flex;align-items:center;gap:4px;padding:8px 11px;background:var(--text);border:0;border-radius:999px;box-shadow:0 0 32px rgba(0,0,0,0.02);cursor:pointer;font-family:inherit;color:var(--surface);line-height:1;transition:opacity 0.18s;-webkit-tap-highlight-color:transparent;}"
    "@media (hover:hover){.gnb-toc-btn:hover{opacity:0.85;}}"
    ".gnb-toc-btn:active{opacity:0.75;}"
    ".gnb-toc-label{font-weight:500;font-size:13px;}"
    ".gnb-toc-progress{display:inline-flex;align-items:center;background:transparent;padding:0;border-radius:0;color:inherit;font-variant-numeric:tabular-nums;font-weight:700;font-size:14px;letter-spacing:0.28px;}"
    # Progress fill — bottom of GNB, no track/guide-line
    ".gnb-progress-fill{position:absolute;bottom:0;left:0;height:2px;width:0;background:var(--text);transition:width 0.1s linear;pointer-events:none;}"
    "body.toc-open{overflow:hidden;}"
    ".toc-panel{position:fixed;inset:0;z-index:300;visibility:hidden;pointer-events:none;}"
    ".toc-panel.open{visibility:visible;pointer-events:auto;}"
    ".toc-overlay{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);opacity:0;transition:opacity 0.25s ease;}"
    ".toc-panel.open .toc-overlay{opacity:1;}"
    ".toc-drawer{position:absolute;top:0;left:0;right:0;bottom:0;background:var(--surface);transform:translateY(100%);transition:transform 0.38s cubic-bezier(0.32,0.72,0,1);display:flex;flex-direction:column;padding-top:env(safe-area-inset-top,0px);}"
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
    ".toc-num{font-size:16px;line-height:1.5;font-weight:500;color:rgba(0,0,0,0.32);flex-shrink:0;min-width:24px;font-variant-numeric:tabular-nums;}"
    ".toc-text{font-size:16px;line-height:1.5;color:rgba(0,0,0,0.32);word-break:keep-all;font-weight:500;}"
    "@media (prefers-color-scheme:dark){.toc-num,.toc-text{color:rgba(255,255,255,0.32);}}"
    ".toc-item.active .toc-num,.toc-item.active .toc-text{color:var(--text);font-weight:700;}"
    # article-label: editorial kicker style (just numbering, no chip)
    ".article-label{display:block;margin-bottom:10px;padding:0;background:transparent;border:0;border-radius:0;font-size:15px;font-weight:700;letter-spacing:0.04em;color:var(--text);font-variant-numeric:tabular-nums;line-height:1;text-transform:none;}"
    ".link-box{padding:8px 12px;}"
    # agit-cta + back-to-top: 2-col flex with identical outline button design
    ".agit-cta{display:flex;gap:10px;margin:0 20px;border-top:1px solid var(--line);padding:20px 0 28px;text-align:left;}"
    ".back-to-top,.agit-cta-btn{flex:1;display:inline-flex;align-items:center;justify-content:center;width:auto;height:44px;padding:0 16px;background:var(--text);color:var(--surface) !important;border:0;border-radius:8px;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;text-decoration:none;letter-spacing:-0.01em;transition:opacity 0.18s;-webkit-tap-highlight-color:transparent;}"
    "@media (hover:hover){"
        ".back-to-top:hover,.agit-cta-btn:hover{opacity:0.85;}"
    "}"
    ".back-to-top:active,.agit-cta-btn:active{opacity:0.75;}"
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
    # Digest intro section (article count + reading time + tagline)
    ".digest-intro{padding:20px 0 28px;border-bottom:1px solid var(--line);}"
    ".digest-meta{display:flex;gap:8px;font-size:13px;color:var(--text4);margin:0 0 14px;font-weight:500;font-variant-numeric:tabular-nums;}"
    ".digest-summary{font-size:17px;line-height:1.6;color:var(--text);letter-spacing:-0.01em;word-break:keep-all;margin:0;}"
    "@media (min-width:768px){.digest-intro{padding:32px 0 36px;}.digest-summary{font-size:18px;}}"
    # PC FAB: 우하단 floating 두 버튼 (맨위로 + 아지트로). 1200+에서만 노출, 스크롤 후 등장.
    ".pc-fabs{display:none;}"
    "@media (min-width:1200px){.gnb-inner{max-width:1320px;margin-left:auto;margin-right:auto;padding:0 40px;bottom:0;}.agit-cta{display:none;}"
        # FAB right 좌표 = 콘텐츠 우측 가장자리에 정렬 (content max-width 1320 - padding 40)
        ".pc-fabs{display:grid;grid-template-columns:max-content;justify-items:stretch;gap:10px;position:fixed;bottom:32px;right:max(32px,calc(50vw - 620px));z-index:50;opacity:0;transform:translateY(8px);pointer-events:none;transition:opacity 0.25s,transform 0.25s;}"
        ".pc-fabs.visible{opacity:1;transform:translateY(0);pointer-events:auto;}"
        ".pc-fab{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:50px;padding:0 20px 0 18px;background:var(--text);color:var(--surface);border:0;border-radius:999px;font-family:'Pretendard',inherit;font-size:15px;font-weight:700;letter-spacing:-0.15px;cursor:pointer;text-decoration:none;box-shadow:0 6px 6px rgba(0,0,0,0.08);transition:opacity 0.18s,transform 0.18s,box-shadow 0.18s;-webkit-tap-highlight-color:transparent;}"
        ".pc-fab svg{flex-shrink:0;display:block;}"
        ".pc-fab:hover{opacity:0.92;transform:translateY(-1px);box-shadow:0 8px 12px rgba(0,0,0,0.12);}"
        ".pc-fab:active{opacity:0.85;transform:translateY(0);box-shadow:0 4px 4px rgba(0,0,0,0.06);}"
        ".digest-intro{grid-column:1 / -1;padding:36px 0 40px;}"
        # Subgrid: align all sections across cards in same row
        # minmax(0,1fr) prevents grid items from overflowing column (default min-width:auto bug)
        ".article-item{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:subgrid;grid-row:span 8;}"
        ".article-item > *{min-width:0;}"
    "}"
    "@media (min-width:1600px){.gnb-inner{max-width:1800px;margin-left:auto;margin-right:auto;}.pc-fabs{right:max(32px,calc(50vw - 860px));}}"
    "@media (prefers-color-scheme:dark) and (min-width:1200px){.pc-fab{box-shadow:0 6px 12px rgba(0,0,0,0.5);}}"
    # 기사 제목/썸네일/요약 영역도 원문으로 이동 (link-box는 기존 그대로)
    ".article-title.clickable-link,.article-summary.clickable-link,.image-frame.clickable-link,.bullet-list.clickable-link{cursor:pointer;}"
    # 앵커 점프 시 타깃 카드 outline ring 페이드 (PC 2열 그리드 이상)
    ":root{--gnb-flash:#05ac36;}"
    "@media (prefers-color-scheme:dark){:root{--gnb-flash:#34C759;}}"
    "@keyframes article-flash{0%{box-shadow:0 0 0 4px var(--gnb-flash);}100%{box-shadow:0 0 0 0 transparent;}}"
    "@media (min-width:1200px){.article-item.flash-target{border-radius:8px;animation:article-flash 1.4s ease-out;}}"
)

GNB_HTML_BODY = (
    '<nav class="gnb">'
    '<div class="gnb-inner">'
    '<a href="#top" class="gnb-brand" data-gnb-top>'
    '<span class="gnb-brand-name">트렌드림</span>'
    '<span class="gnb-date"></span>'
    '</a>'
    '<button class="gnb-toc-btn" type="button" aria-expanded="false" aria-controls="toc-panel">'
    '<span class="gnb-toc-label">목차</span>'
    '<span class="gnb-toc-progress"><span class="cur">1</span>/<span class="tot">0</span></span>'
    '</button>'
    '</div>'
    '<div class="gnb-progress-fill"></div>'
    '</nav>'
    '<aside id="toc-panel" class="toc-panel" aria-hidden="true">'
    '<div class="toc-overlay"></div>'
    '<div class="toc-drawer">'
    '<div class="toc-header"><span class="toc-title">목차</span><button type="button" class="toc-close" aria-label="목차 닫기">×</button></div>'
    '<ol class="toc-list"></ol>'
    '</div></aside>'
)

GNB_JS_BODY = '''<script>(function(){
// Naver-style trick: set theme-color content to empty so iOS Safari renders
// status bar transparent over page content (instead of solid theme-color tint).
var tcs=document.querySelectorAll('meta[name="theme-color"]');
for(var i=0;i<tcs.length;i++)tcs[i].setAttribute('content','');
if(!tcs.length){
var m=document.createElement('meta');m.setAttribute('name','theme-color');m.setAttribute('content','');document.head.appendChild(m);
}
var arts=document.querySelectorAll('.article-item');
if(!arts.length)return;
// PC FAB: 우하단 floating "맨위로" + "아지트로 →" (1200+ only, scroll-to-show)
if(!document.querySelector('.pc-fabs')){
var agitBtn=document.querySelector('.agit-cta-btn');
var agitHref=agitBtn?agitBtn.getAttribute('href'):'#';
var fabs=document.createElement('div');
fabs.className='pc-fabs';
fabs.setAttribute('aria-hidden','true');
var upSvg='<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1V15M13 6L8 1L3 6"/></svg>';
var returnSvg='<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 2L3 5L6 8"/><path d="M3 5H10C10.7956 5 11.5587 5.31607 12.1213 5.87868C12.6839 6.44129 13 7.20435 13 8V14"/></svg>';
fabs.innerHTML='<button class="pc-fab" type="button" data-pc-top>'+upSvg+'<span>맨 위로</span></button><a class="pc-fab" href="'+agitHref+'">'+returnSvg+'<span>아지트로</span></a>';
document.body.appendChild(fabs);
var pcTop=fabs.querySelector('[data-pc-top]');
if(pcTop)pcTop.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});pcTop.blur();});
function checkPcScroll(){if(window.scrollY>200){fabs.classList.add('visible');}else{fabs.classList.remove('visible');}}
window.addEventListener('scroll',checkPcScroll,{passive:true});
checkPcScroll();
}
// Insert digest intro at top of article-wrap (count + reading time)
var artWrap=document.querySelector('.article-wrap');
if(artWrap&&!document.querySelector('.digest-intro')){
var totalChars=0;
for(var ai=0;ai<arts.length;ai++)totalChars+=(arts[ai].textContent||'').length;
var readMins=Math.max(1,Math.round(totalChars/700));
var titles=[];
for(var ti=0;ti<Math.min(arts.length,3);ti++){var tt=arts[ti].querySelector('.article-title');if(tt)titles.push(tt.textContent.trim());}
var summaryText=titles.length>0?titles.join(', ')+' 등 '+arts.length+'개의 이야기를 담았어요.':'오늘의 '+arts.length+'개 기사를 확인해보세요.';
var intro=document.createElement('section');
intro.className='digest-intro';
intro.innerHTML='<div class="digest-meta"><span>'+arts.length+'개 기사</span><span>·</span><span>약 '+readMins+'분 읽기</span></div><p class="digest-summary">'+summaryText+'</p>';
artWrap.insertBefore(intro,artWrap.firstElementChild);
}
var gnb=document.querySelector('.gnb');
var tocList=document.querySelector('.toc-list');
var tocBtn=document.querySelector('.gnb-toc-btn');
var tocPanel=document.getElementById('toc-panel');
var tocClose=document.querySelector('.toc-close');
var tocOverlay=document.querySelector('.toc-overlay');
var curEl=document.querySelector('.gnb-toc-progress .cur');
var totEl=document.querySelector('.gnb-toc-progress .tot');
var brand=document.querySelector('[data-gnb-top]');
var dateEl=document.querySelector('.gnb-date');
var DAYS=['일','월','화','수','목','금','토'];
var pm=location.pathname.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
if(pm&&dateEl){
var y=parseInt(pm[1],10),mo=parseInt(pm[2],10),d=parseInt(pm[3],10);
var dow=DAYS[new Date(y,mo-1,d).getDay()];
dateEl.textContent=(y%100)+'.'+mo+'.'+d+' ('+dow+')';
}
function updateGnbH(){var g=document.querySelector('.gnb');if(g){document.documentElement.style.setProperty('--gnb-h',g.offsetHeight+'px');}}
updateGnbH();
window.addEventListener('resize',updateGnbH);
var progressFill=document.querySelector('.gnb-progress-fill');
function updateProgress(){
if(!progressFill)return;
var d=document.documentElement;
var total=d.scrollHeight-window.innerHeight;
var cur=window.scrollY||d.scrollTop;
var pct=total>0?Math.min(100,(cur/total)*100):0;
progressFill.style.width=pct+'%';
}
updateProgress();
window.addEventListener('scroll',updateProgress,{passive:true});
window.addEventListener('resize',updateProgress);
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
// 제목/썸네일/요약 영역도 원문 링크로 이동
var lk=art.querySelector('.article-link');
var url=lk?lk.getAttribute('href'):'';
if(url){
var targets=['.article-title','.article-summary','.image-frame','.bullet-list'];
for(var ti2=0;ti2<targets.length;ti2++){
var el=art.querySelector(targets[ti2]);
if(!el)continue;
el.classList.add('clickable-link');
el.addEventListener('click',function(u){return function(e){
if(window.getSelection&&window.getSelection().toString().length>0)return;
window.open(u,'_blank','noopener');
};}(url));
}
}
});
totEl.textContent=arts.length;
// 외부 hash 진입 / 페이지 내 목차 클릭 모두에서 타깃 카드 flash
function flashTarget(){if(!location.hash)return;var t=document.querySelector(location.hash);if(!t||!t.classList||!t.classList.contains('article-item'))return;t.classList.remove('flash-target');void t.offsetWidth;t.classList.add('flash-target');}
if(location.hash){var tgt=document.querySelector(location.hash);if(tgt)setTimeout(function(){tgt.scrollIntoView();flashTarget();},0);}
window.addEventListener('hashchange',function(){setTimeout(flashTarget,50);});
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

def add_article_anchor_ids(content):
    # 외부 hash 링크(#article-N)가 페이지 로드 직후 즉시 점프되도록
    # 빌드 타임에 article-item에 id를 박아둠. (런타임 JS도 동일 id를 덮어쓰지만
    # 그 시점엔 이미 브라우저가 hash 처리를 끝낸 후라 외부 진입 시 점프 실패함)
    counter = {'n': 0}
    def repl(m):
        counter['n'] += 1
        return f'<article id="article-{counter["n"]}" class="article-item"'
    return re.sub(r'<article\s+class="article-item"', repl, content)

def ensure_viewport_fit_cover(content):
    # Naver/Daum approach: NO viewport-fit=cover.
    # iOS Safari natively renders translucent status bar that samples page content.
    # If viewport-fit=cover is present, remove it.
    def repl(m):
        attrs = m.group(0)
        cm = re.search(r'content\s*=\s*"([^"]*)"', attrs)
        if not cm:
            return attrs
        val = cm.group(1)
        # Strip viewport-fit=cover (and clean trailing/leading commas/spaces)
        new_val = re.sub(r',?\s*viewport-fit\s*=\s*[^,]+', '', val).strip().strip(',').strip()
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
    content = add_article_anchor_ids(content)
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
