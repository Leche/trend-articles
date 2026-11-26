/* 트렌드림 아침 브리핑 — 실사 영상 다큐 톤
 * 화면 전체는 색 보정한 실사 클립(Pixabay)과 일부 AI 실사풍 이미지. 글자는 최소로:
 * 기사 시작의 하단 타이틀, 핵심 숫자 한 번, 기사 이미지 카드 한 번, 구절 자막.
 * 입력: plan.js(window.PLAN — plan.py 가 timeline.json 으로 만든다)
 */
const { ease, prog, kf, clamp, lerp, split, stagger, css, h, cue } = REEL;
const PL = window.PLAN, SEGS = PL.segs, SHOTS = PL.shots, SUBS = PL.subs, META = PL.meta;
const DUR = REEL.TL.duration;
REEL.config({ duration: DUR, fps: 30, width: 1920, height: 1080, audio: '../audio/mix.wav' });
const W = 1920, H = 1080, HALF = 0.5 / 30;
const ARTS = SEGS.filter(s => s.num);
const segAt = t => SEGS.find(s => t >= s.start - HALF && t < s.end - HALF) || SEGS[SEGS.length - 1];

/* ── 프레임 로더: 필요한 JPG 만 불러오고, 렌더러가 다 불러올 때까지 기다리게 한다 ── */
const cache = new Map(); let pend = [];
function frame(src) {
  let im = cache.get(src);
  if (im) { cache.delete(src); cache.set(src, im); return im._ok ? im : null; }
  im = new Image(); im._ok = false;
  pend.push(new Promise(r => {
    im.onload = () => im.decode().catch(() => null).then(() => { im._ok = true; r(); });
    im.onerror = () => { console.error('[REEL] 프레임 로드 실패', src); im._ok = true; r(); };
  }));
  im.src = src; cache.set(src, im);
  if (cache.size > 160) cache.delete(cache.keys().next().value);
  return null;
}
const seek0 = window.__seek;
window.__seek = async t => {
  seek0(t);
  for (let g = 0; g < 4 && pend.length; g++) { const ps = pend; pend = []; await Promise.all(ps); seek0(t); }
};
const stills = {};
SHOTS.filter(s => s.kind === 'img').forEach(s => { stills[s.src] = REEL.img(s.src); });
const thumbs = {};
ARTS.forEach(s => { thumbs[s.id] = REEL.img(`../assets/src/${s.thumb}`); });

/* ── 장면 1: 필름(배경 영상) ── */
REEL.scene({
  id: 'film', start: 0, end: DUR,
  setup(el) {
    const c = this.cv = h('canvas', '', el); c.width = W; c.height = H;
    css(c, { position: 'absolute', left: 0, top: 0, width: W + 'px', height: H + 'px' });
    this.g = c.getContext('2d'); this.g.imageSmoothingQuality = 'high';
    const s = this.small = document.createElement('canvas'); s.width = 192; s.height = 108; this.sg = s.getContext('2d');
    this.grain = [0, 1, 2, 3].map(k => { const c2 = document.createElement('canvas'); c2.width = 640; c2.height = 360; const x = c2.getContext('2d'), d = x.createImageData(640, 360);
      for (let i = 0; i < 640 * 360; i++) { const v = 128 + (REEL.rand(i, 17 + k) - 0.5) * 120; d.data[i * 4] = d.data[i * 4 + 1] = d.data[i * 4 + 2] = v; d.data[i * 4 + 3] = 255; }
      x.putImageData(d, 0, 0); return c2; });
    // 비네트 + 아래쪽 어둠(자막·타이틀 가독성)
    css(h('div', 'full', el), { background: 'radial-gradient(ellipse 75% 70% at 50% 46%, rgba(0,0,0,0) 55%, rgba(0,0,0,.42) 100%)' });
    css(h('div', 'full', el), { background: 'linear-gradient(to top, rgba(0,0,0,.72) 0%, rgba(0,0,0,.32) 22%, rgba(0,0,0,0) 42%)' });
    css(h('div', 'full', el), { background: 'linear-gradient(to bottom, rgba(0,0,0,.35) 0%, rgba(0,0,0,0) 16%)' });
  },
  shotImg(sh, t) {
    if (sh.kind === 'img') return stills[sh.src];
    const i = clamp(Math.floor((t - sh.a) * 30) + 1, 1, sh.n);
    return frame(`${sh.dir}${String(i).padStart(5, '0')}.jpg`);
  },
  render(lt, ctx) {
    const t = ctx.t, g = this.g, T = t + HALF;
    const sh = SHOTS.find(s => T >= s.a && T < s.b) || SHOTS[SHOTS.length - 1];
    const im = this.shotImg(sh, t);
    g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
    if (!im) return;
    const p = clamp((t - sh.a) / (sh.b - sh.a));
    const sc = sh.kind === 'img' ? lerp(1.0, 1.08, ease.inOutSine(p)) : lerp(1.0, sh.seg === 'intro' || sh.seg === 'outro' ? 1.08 : 1.045, p);
    const dx = sh.kind === 'img' ? lerp(-18, 18, ease.inOutSine(p)) : 0;
    const iw = sh.kind === 'img' ? im.naturalWidth : W, ih = sh.kind === 'img' ? im.naturalHeight : H;
    const k = Math.max(W / iw, H / ih) * sc, dw = iw * k, dh = ih * k;
    const seg = segAt(t);
    // 기사 이미지 카드가 떠 있는 동안 배경은 흐리고 어둡게
    const ev = seg.ev ? prog(t, seg.ev[0], 0.45, ease.inOutCubic) * (1 - prog(t, seg.ev[1] - 0.35, 0.4, ease.inOutCubic)) : 0;
    const key = seg.K ? kf(t, [[seg.K - 0.15, 0], [seg.K + 0.25, 1, ease.outCubic], [Math.min(seg.K + 3.1, seg.end - 0.5), 1], [Math.min(seg.K + 3.5, seg.end - 0.15), 0, ease.inCubic]]) : 0;
    const intro = t < SEGS[0].hook - HALF ? 0.22 : t < SEGS[1].start - HALF ? 0.4 : 0, out = t > SEGS[SEGS.length - 1].start + 3.2 ? prog(t, SEGS[SEGS.length - 1].start + 3.2, 1.0) * 0.4 : 0;
    g.globalAlpha = 1;
    g.drawImage(im, (W - dw) / 2 + dx, (H - dh) / 2, dw, dh);
    if (ev > 0.001) {
      this.sg.drawImage(this.cv, 0, 0, 192, 108);
      g.globalAlpha = ev; g.drawImage(this.small, 0, 0, W, H); g.globalAlpha = 1;
    }
    const dim = Math.max(ev * 0.38, key * 0.34, intro, out);
    if (dim > 0) { g.fillStyle = `rgba(0,0,0,${dim})`; g.fillRect(0, 0, W, H); }
    // 처음 0.6초 페이드 인, 마지막 0.8초 페이드 아웃
    g.globalCompositeOperation = 'overlay'; g.globalAlpha = 0.09;
    g.drawImage(this.grain[Math.floor(t * 30) % 4], 0, 0, W, H); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    const fade = Math.max((1 - prog(t, 0, 0.6)) * 0.7, prog(t, DUR - 0.9, 0.8));
    if (fade > 0) { g.fillStyle = `rgba(0,0,0,${fade})`; g.fillRect(0, 0, W, H); }
  },
});

/* ── 글자 공통 ── */
const SH = '0 2px 18px rgba(0,0,0,.45), 0 1px 3px rgba(0,0,0,.5)';
function rise(spans, t, t0, each = 0.05, dur = 0.55, out = 0) {
  spans.forEach((c, i) => {
    const p = stagger(t, t0, each, dur, i, ease.snap);
    css(c, { transform: `translateY(${((1 - p) * 110 - out * 110).toFixed(1)}%)`, opacity: p > 0 && out < 0.999 ? 1 : 0 });
  });
}

/* ── 장면 2: 오프닝 타이틀과 훅 ── */
REEL.scene({
  id: 'open', start: 0, end: SEGS[1].start,
  setup(el) {
    this.title = h('div', 'center', el, '트렌드림');
    css(this.title, { top: '372px', fontSize: '168px', fontWeight: 800, letterSpacing: '-0.045em', lineHeight: '1', color: '#fff', textShadow: SH });
    this.tc = split(this.title, 'char', { mask: true });
    this.sub = h('div', 'center', el, `${META.dateLabel} &nbsp;·&nbsp; 아침 브리핑`);
    css(this.sub, { top: '574px', fontSize: '34px', fontWeight: 500, letterSpacing: '0.02em', color: 'rgba(255,255,255,.86)', textShadow: SH });
    const v = REEL.TL.vo.find(x => x.id === 'intro'), ws = v.words;
    const hi = Math.max(0, ws.findIndex(w => w[1] >= cue('hook', 5.8) - 0.05));
    this.hw = []; this.hook = h('div', 'a', el); css(this.hook, { left: '150px', top: '640px', width: '1500px' });
    META.hookLines.map(x => [x]).forEach(([ln], li) => {
      const d = h('div', '', this.hook, ln);
      css(d, { fontSize: '64px', fontWeight: 700, letterSpacing: '-0.035em', lineHeight: '1.3', color: '#fff', textShadow: SH, whiteSpace: 'nowrap' });
      split(d, 'word', { mask: true }).forEach(w => { const idx = hi + this.hw.length; this.hw.push({ w, t: ws[Math.min(idx, ws.length - 1)][1], li }); });
    });
  },
  render(lt, ctx) {
    const t = ctx.t, B = cue('brand', 3.5), tout = prog(t, cue('hook', 5.8) - 0.55, 0.45, ease.exit);
    rise(this.tc, t, 0.7, 0.08, 0.8, tout);
    this.title.style.fontWeight = lerp(300, 800, prog(t, 0.7, B - 0.6, ease.inOutCubic)).toFixed(0);
    const s = prog(t, 1.6, 0.6, ease.snap) * (1 - tout);
    css(this.sub, { opacity: s.toFixed(3), transform: `translateY(${((1 - s) * 14).toFixed(1)}px)` });
    const ho = prog(t, SEGS[1].start - 0.55, 0.4, ease.exit);
    this.hw.forEach(({ w, t: wt, li }) => {
      const p = prog(t, wt - 0.12, 0.5, ease.snap);
      css(w, { transform: `translateY(${((1 - p) * 110 - ho * 110).toFixed(1)}%)`, opacity: p > 0 ? 1 : 0 });
    });
  },
});

/* ── 장면 3: 본편 UI(브랜드·번호·하단 타이틀·핵심 숫자·기사 이미지·자막) ── */
REEL.scene({
  id: 'ui', start: SEGS[1].start - 0.2, end: SEGS[SEGS.length - 1].start + 0.5,
  setup(el) {
    this.brand = h('div', 'a', el, `트렌드림<span style="font-weight:500;font-size:25px;opacity:.78;margin-left:14px;letter-spacing:.04em">${META.shortLabel}</span>`);
    css(this.brand, { left: '72px', top: '52px', fontSize: '34px', fontWeight: 800, letterSpacing: '-0.03em', color: '#fff', textShadow: SH });
    this.count = h('div', 'a', el, ''); css(this.count, { right: '72px', top: '56px', fontFamily: 'var(--mono)', fontSize: '30px', fontWeight: 500, color: 'rgba(255,255,255,.8)', textShadow: SH });
    this.L = ARTS.map(s => {
      const box = h('div', 'a', el); css(box, { left: '120px', top: '730px' });
      const meta = h('div', '', box, `<span style="display:inline-block;width:34px;height:3px;background:var(--accent);vertical-align:middle;margin-right:16px;transform-origin:0 50%" class="bar"></span>${String(s.num).padStart(2, '0')} &nbsp;·&nbsp; ${s.src}`);
      css(meta, { fontFamily: 'var(--mono)', fontSize: '28px', fontWeight: 500, color: 'rgba(255,255,255,.9)', textShadow: SH, marginBottom: '14px', whiteSpace: 'nowrap' });
      const hd = h('div', '', box, s.head); css(hd, { fontSize: '66px', fontWeight: 760, letterSpacing: '-0.035em', lineHeight: '1.15', color: '#fff', textShadow: SH, whiteSpace: 'nowrap' });
      const ws = split(hd, 'word', { mask: true });
      let key = null, kc = null, cap = null;
      if (s.key) {
        key = h('div', 'center', el, s.key); css(key, { top: '330px', fontSize: s.key.length > 4 ? '170px' : '210px', fontWeight: 800, letterSpacing: '-0.045em', lineHeight: '1', color: '#fff', textShadow: SH, fontVariantNumeric: 'tabular-nums' });
        kc = split(key, 'char', { mask: true });
        cap = h('div', 'center', el, s.cap); css(cap, { top: '572px', fontSize: '46px', fontWeight: 600, letterSpacing: '-0.02em', color: 'rgba(255,255,255,.9)', textShadow: SH });
      }
      const card = h('div', 'a', el); css(card, { left: '420px', top: '150px', width: '1080px', height: '675px', borderRadius: '18px', overflow: 'hidden',
        boxShadow: '0 30px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.14)', transformOrigin: '50% 60%' });
      const im = thumbs[s.id]; card.appendChild(im); css(im, { width: '100%', height: '100%', objectFit: 'cover', filter: 'saturate(.8) brightness(.88) contrast(.97)' });
      const clab = null;
      return { s, box, meta, bar: meta.querySelector('.bar'), ws, key, kc, cap, card, clab };
    });
    this.subEl = h('div', 'center', el, ''); css(this.subEl, { top: '948px', fontSize: '48px', fontWeight: 600, letterSpacing: '-0.015em', color: '#fff', textShadow: '0 2px 10px rgba(0,0,0,.7), 0 0 2px rgba(0,0,0,.6)' });
  },
  render(lt, ctx) {
    const t = ctx.t, seg = segAt(t);
    const top = prog(t, SEGS[1].start + 0.2, 0.5) * (1 - prog(t, SEGS[SEGS.length - 1].start - 0.2, 0.4));
    this.brand.style.opacity = top.toFixed(3);
    this.count.textContent = seg.num ? `${String(seg.num).padStart(2, '0')} / ${String(ARTS.length).padStart(2, '0')}` : '';
    this.count.style.opacity = (top * (seg.num ? 1 : 0)).toFixed(3);
    let titleOn = false, keyOn = false;
    this.L.forEach(o => {
      const s = o.s, on = t > s.start - 0.3 && t < s.end + 0.3;
      o.box.style.display = on ? '' : 'none';
      [o.card, o.key, o.cap].forEach(x => x && (x.style.display = on ? '' : 'none'));
      if (!on) return;
      // 하단 타이틀: 기사 시작 0.35초 ~ 4.8초
      const a0 = s.start + 0.35, aOut = prog(t, s.start + 4.7, 0.4, ease.exit);
      if (t < s.start + 5.2) titleOn = true;
      if (s.K && t > s.K - 0.2 && t < Math.min(s.K + 3.5, s.end)) keyOn = true;
      const m = prog(t, a0, 0.45, ease.snap);
      css(o.meta, { opacity: (m * (1 - aOut)).toFixed(3), transform: `translateY(${((1 - m) * 12).toFixed(1)}px)` });
      o.bar.style.transform = `scaleX(${prog(t, a0, 0.6, ease.swift).toFixed(3)})`;
      rise(o.ws, t, a0 + 0.12, 0.05, 0.55, aOut);
      // 핵심 숫자
      if (o.key) {
        const K = s.K, kOut = prog(t, Math.min(K + 3.1, s.end - 0.5), 0.38, ease.exit);
        rise(o.kc, t, K - 0.12, 0.05, 0.6, kOut);
        const c = prog(t, K + 0.2, 0.5, ease.snap) * (1 - kOut);
        css(o.cap, { opacity: c.toFixed(3), transform: `translateY(${((1 - c) * 14).toFixed(1)}px)` });
      }
      // 기사 이미지 카드
      const ev = prog(t, s.ev[0], 0.55, ease.snap), evo = prog(t, s.ev[1] - 0.35, 0.35, ease.exit);
      const life = clamp((t - s.ev[0]) / (s.ev[1] - s.ev[0]));
      css(o.card, { opacity: (ev * (1 - evo)).toFixed(3),
        transform: `perspective(1800px) translateY(${((1 - ev) * 40 - evo * 24).toFixed(1)}px) rotateY(${lerp(-7, 5, life).toFixed(2)}deg) rotateX(${lerp(3, -1, life).toFixed(2)}deg) scale(${lerp(0.97, 1.01, life).toFixed(4)})` });
    });
    // 자막(하단 타이틀이 떠 있는 동안은 숨김)
    const sub = SUBS.find(x => t >= x.t0 && t < x.t1);
    const want = sub && !titleOn && !keyOn ? sub.text : '';
    if (this.subEl.textContent !== want) this.subEl.textContent = want;
    const sp = sub ? prog(t, sub.t0, 0.12) * (1 - prog(t, sub.t1 - 0.1, 0.1)) : 0;
    this.subEl.style.opacity = (sp * top).toFixed(3);
  },
});

/* ── 장면 4: 갈림길 ── */
const BR = SEGS.find(s => s.id === 'branch');
REEL.scene({
  id: 'branch', start: BR.start, end: BR.end,
  setup(el) {
    this.t = h('div', 'center', el, '이것도 함께 실렸어요'); css(this.t, { top: '446px', fontSize: '104px', fontWeight: 760, letterSpacing: '-0.04em', color: '#fff', textShadow: SH });
    this.c = split(this.t, 'word', { mask: true });
    this.s = h('div', 'center', el, '06 — 08'); css(this.s, { top: '590px', fontFamily: 'var(--mono)', fontSize: '28px', color: 'rgba(255,255,255,.8)', textShadow: SH });
  },
  render(lt, ctx) {
    const t = ctx.t, out = prog(t, BR.end - 0.45, 0.35, ease.exit);
    rise(this.c, t, cue('line.branch', BR.start + 0.4) - 0.15, 0.1, 0.55, out);
    const q = prog(t, BR.start + 0.7, 0.4) * (1 - out); this.s.style.opacity = q.toFixed(3);
  },
});

/* ── 장면 5: 엔드카드 ── */
const OU = SEGS[SEGS.length - 1];
const BOKEH = SHOTS.filter(x => x.seg === 'outro')[1].a;
REEL.scene({
  id: 'end', start: BOKEH, end: DUR,
  setup(el) {
    this.list = h('div', 'a', el); css(this.list, { left: '150px', top: '250px' });
    this.rows = ARTS.map(s => {
      const r = h('div', '', this.list, `<span style="font-family:var(--mono);font-size:24px;opacity:.65;margin-right:26px">${String(s.num).padStart(2, '0')}</span>${s.head}`);
      css(r, { fontSize: '36px', fontWeight: 620, letterSpacing: '-0.02em', lineHeight: '1.0', margin: '0 0 30px', color: '#fff', textShadow: SH, whiteSpace: 'nowrap' });
      return r;
    });
    this.brand = h('div', 'a', el); css(this.brand, { left: '1290px', top: '360px' });
    this.bt = h('div', '', this.brand, '트렌드림'); css(this.bt, { fontSize: '112px', fontWeight: 800, letterSpacing: '-0.045em', lineHeight: '1', color: '#fff', textShadow: SH });
    this.bc = split(this.bt, 'char', { mask: true });
    this.bl = h('div', '', this.brand); css(this.bl, { margin: '34px 0 30px', width: '84px', height: '4px', background: 'var(--accent)', transformOrigin: '0 50%' });
    this.bx = h('div', '', this.brand, '기사 전체는<br>아지트 본문에서'); css(this.bx, { fontSize: '44px', fontWeight: 700, letterSpacing: '-0.03em', lineHeight: '1.35', color: '#fff', textShadow: SH });
    this.cr = h('div', 'a', el, '영상 Pixabay &nbsp;·&nbsp; 일부 이미지 AI 생성'); css(this.cr, { right: '72px', bottom: '54px', fontSize: '20px', color: 'rgba(255,255,255,.55)' });
  },
  render(lt, ctx) {
    const t = ctx.t, t0 = BOKEH + 0.25;
    this.rows.forEach((r, i) => { const p = prog(t, t0 + i * 0.09, 0.5, ease.snap); css(r, { opacity: p.toFixed(3), transform: `translateX(${((1 - p) * -24).toFixed(1)}px)` }); });
    rise(this.bc, t, t0 + 0.9, 0.07, 0.6);
    this.bl.style.transform = `scaleX(${prog(t, t0 + 1.3, 0.6, ease.swift).toFixed(3)})`;
    const x = prog(t, t0 + 1.5, 0.5, ease.snap); css(this.bx, { opacity: x.toFixed(3), transform: `translateY(${((1 - x) * 14).toFixed(1)}px)` });
    this.cr.style.opacity = prog(t, t0 + 1.8, 0.6).toFixed(3);
  },
});
