(() => {
  'use strict';
  const body = document.body;
  const article = document.querySelector('#article-body');
  const root = document.documentElement;
  const $ = selector => document.querySelector(selector);
  const storageKey = 'knowledge-reader-v2';
  const defaults = {version:3,theme:'white',texture:'none',size:18,marginPercent:10,line:1.9,indent:false,font:'sans',tocHidden:false};
  const choice = (v, values, fallback) => values.includes(v) ? v : fallback;
  const bounded = (v,lo,hi,fallback,step=1) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.max(lo,Math.min(hi,Math.round(n/step)*step)) : fallback;
  };
  let settings = {...defaults,marginPercent:bounded(body.dataset.margin,0,40,10)};
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(storageKey)||'null'); } catch { /* 无存储权限时仍可阅读。 */ }
  if (stored && typeof stored === 'object') settings = {
    theme:choice(stored.theme,['white','paper','green','dark'],'white'),
    version:3,texture:choice(stored.texture,['none','grain'],'none'),
    size:bounded(stored.size,16,36,18),marginPercent:bounded(stored.marginPercent,0,40,settings.marginPercent),
    line:bounded(stored.line,1.4,2.4,1.9,.1),indent:stored.indent===true,
    font:choice(stored.font,['sans','serif','kai'],'sans'),tocHidden:stored.tocHidden===true
  };
  // 将上一版“最大宽度 + px 边距”换算成一个比例，只迁移一次。
  if (stored && stored.marginPercent === undefined && stored.margin !== undefined) {
    const rail = innerWidth > 900 && !settings.tocHidden ? parseFloat(getComputedStyle(body).getPropertyValue('--rail')) : 0;
    const available = Math.max(1,root.clientWidth-rail);
    const oldLimit = {clean:1060,compact:1320,book:860}[stored.layout] || 1060;
    const oldMargin = bounded(stored.margin,16,120,40);
    const padding = innerWidth <= 900 ? Math.min(oldMargin,innerWidth*.08) : oldMargin;
    settings.marginPercent = bounded((1-Math.min(oldLimit,Math.max(0,available-padding*2))/available)*50,0,40,10);
  }
  function save() {
    try { localStorage.setItem(storageKey,JSON.stringify(settings)); $('#settings-save-note').textContent='设置会在此浏览器中自动记住'; }
    catch { $('#settings-save-note').textContent='当前设置已生效；此浏览器暂不允许保存'; }
  }
  function apply(preservePosition=false) {
    const anchor = preservePosition && scrollY>120 ? [...article.children].find(el=>el.getBoundingClientRect().bottom>90) : null;
    const offset = anchor ? anchor.getBoundingClientRect().top : 0;
    root.dataset.theme=settings.theme;
    body.dataset.texture=settings.texture;
    body.dataset.font=settings.font; body.dataset.indent=String(settings.indent); body.dataset.tocHidden=String(settings.tocHidden);
    body.style.setProperty('--body-size',`${settings.size}px`);
    body.style.setProperty('--side-space',`${settings.marginPercent}%`);
    body.style.setProperty('--leading',String(settings.line));
    $('#texture-select').value=settings.texture; $('#font-select').value=settings.font;
    $('#font-range').value=settings.size; $('#font-size').textContent=`${settings.size} px`;
    $('#font-smaller').disabled=settings.size===16; $('#font-larger').disabled=settings.size===36;
    $('#margin-range').value=settings.marginPercent;
    $('#margin-value').textContent=`每侧 ${settings.marginPercent}%`;
    $('#margin-range').setAttribute('aria-valuetext',`左右各留白 ${settings.marginPercent}%，正文占 ${100-settings.marginPercent*2}%`);
    $('#margin-description').textContent=`正文占阅读区域的 ${100-settings.marginPercent*2}%`;
    document.querySelectorAll('[data-margin-value]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.marginValue)===settings.marginPercent)));
    $('#line-range').value=settings.line; $('#line-value').textContent=`${settings.line.toFixed(1)} 倍`;
    $('#indent-toggle').checked=settings.indent;
    document.querySelectorAll('[data-theme-value]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeValue===settings.theme)));
    $('#toc-toggle').setAttribute('aria-expanded',String(!settings.tocHidden));
    $('#toc-toggle').setAttribute('aria-label',settings.tocHidden?'展开左侧目录':'收起左侧目录');
    if(anchor) window.scrollBy({top:anchor.getBoundingClientRect().top-offset,behavior:'instant'});
    currentId='';
    updateProgress();
  }
  function change(key,value){settings[key]=value;apply(true);save();}
  document.querySelectorAll('[data-theme-value]').forEach(b=>b.addEventListener('click',()=>change('theme',b.dataset.themeValue)));
  $('#texture-select').addEventListener('change',e=>change('texture',e.target.value));
  $('#font-select').addEventListener('change',e=>change('font',e.target.value));
  $('#font-range').addEventListener('input',e=>change('size',Number(e.target.value)));
  $('#margin-range').addEventListener('input',e=>change('marginPercent',Number(e.target.value)));
  document.querySelectorAll('[data-margin-value]').forEach(b=>b.addEventListener('click',()=>change('marginPercent',Number(b.dataset.marginValue))));
  $('#line-range').addEventListener('input',e=>change('line',Number(e.target.value)));
  $('#indent-toggle').addEventListener('change',e=>change('indent',e.target.checked));
  $('#font-smaller').addEventListener('click',()=>change('size',Math.max(16,settings.size-1)));
  $('#font-larger').addEventListener('click',()=>change('size',Math.min(36,settings.size+1)));
  $('#toc-toggle').addEventListener('click',()=>change('tocHidden',!settings.tocHidden));
  $('#settings-reset').addEventListener('click',()=>{settings={...defaults};apply(true);save();});
  const panel=$('#reader-settings'),trigger=$('#settings-open');
  trigger.addEventListener('click',()=>{panel.showModal();trigger.setAttribute('aria-expanded','true');});
  $('#settings-close').addEventListener('click',()=>panel.close());
  panel.addEventListener('close',()=>trigger.setAttribute('aria-expanded','false'));
  panel.addEventListener('click',e=>{const r=panel.getBoundingClientRect();if(e.target===panel&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))panel.close();});
  $('#print-button').addEventListener('click',()=>{panel.close();window.print();});
  const headings = [...article.querySelectorAll('h2[id], h3[id]')];
  const toc = document.querySelector('.toc-rail .toc-list');
  const tocLinks = [...document.querySelectorAll('.toc-list a')];
  const expand = document.querySelector('.toc-expand');
  let currentId = '';
  let scheduled = false;
  function updateProgress() {
    const titleBottom = document.querySelector('.article-header h1').getBoundingClientRect().bottom;
    const toolbarBottom = document.querySelector('.toolbar').getBoundingClientRect().bottom;
    $('#toolbar-title').hidden = titleBottom > toolbarBottom;
    const max = document.documentElement.scrollHeight - innerHeight;
    const ratio = max > 0 ? Math.max(0, Math.min(1, scrollY / max)) : 1;
    document.querySelector('.reading-progress').style.width = `${ratio * 100}%`;
    document.querySelector('#progress-text').textContent = `阅读进度 ${Math.round(ratio * 100)}%`;
    let current = headings[0];
    for (const heading of headings) {
      if (heading.getBoundingClientRect().top <= 110) current = heading;
      else break;
    }
    if (current && current.id !== currentId) {
      currentId = current.id;
      let parent = current.tagName === 'H2' ? current : null;
      if (!parent) for (const h of headings) { if (h === current) break; if (h.tagName === 'H2') parent = h; }
      const parentId = parent ? parent.id : '';
      tocLinks.forEach(link => {
        if (link.hash.slice(1) === currentId) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
        const item = link.closest('.toc-sub');
        if (item) item.classList.toggle('is-open', item.dataset.parent === parentId);
      });
      // 只滚动目录自身，避免 scrollIntoView 带动正文跳动。
      const active = document.querySelector('.toc-rail a[aria-current="location"]');
      if (active && getComputedStyle(document.querySelector('.toc-rail')).display !== 'none') {
        const nav = document.querySelector('.toc-nav');
        const r = active.getBoundingClientRect(), box = nav.getBoundingClientRect();
        if (r.bottom > box.bottom) nav.scrollTop += r.bottom - box.bottom + 20;
        if (r.top < box.top) nav.scrollTop -= box.top - r.top + 20;
      }
    }
  }
  function scheduleProgress() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { updateProgress(); scheduled = false; });
  }
  window.addEventListener('scroll', scheduleProgress, {passive:true});
  window.addEventListener('resize', scheduleProgress);
  window.addEventListener('load', updateProgress);
  expand.addEventListener('click', () => {
    const expanded = toc.dataset.expanded !== 'true';
    toc.dataset.expanded = String(expanded);
    expand.setAttribute('aria-expanded', String(expanded));
    expand.textContent = expanded ? '仅展开当前章节' : '展开全部小节';
  });
  document.querySelectorAll('.mobile-toc a').forEach(link => link.addEventListener('click', () => {
    document.querySelector('.mobile-toc').open = false;
  }));
  const dialog = document.querySelector('#image-dialog');
  const zoom = document.querySelector('#zoom-image');
  document.querySelectorAll('figure img').forEach(img => {
    img.addEventListener('load', scheduleProgress);
    const button = img.closest('.image-button');
    if (!button) return;
    button.addEventListener('click', () => {
      if (typeof dialog.showModal !== 'function') return;
      zoom.src = img.currentSrc || img.src;
      zoom.alt = img.alt;
      document.querySelector('#zoom-description').textContent = img.alt || '原图';
      dialog.showModal();
      document.querySelector('.zoom-scroll').scrollTo(0, 0);
    });
  });
  document.querySelector('.zoom-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => zoom.removeAttribute('src'));
  // 打印时展开补充说明，结束后恢复读者原来的折叠状态。
  let closedDetails = [];
  window.addEventListener('beforeprint', () => {
    closedDetails = [...article.querySelectorAll('details:not([open])')];
    closedDetails.forEach(item => item.open = true);
  });
  window.addEventListener('afterprint', () => closedDetails.forEach(item => item.open = false));
  apply();
  // 迁移后的值写回，避免在不同窗口宽度下反复换算。
  if (stored && stored.marginPercent === undefined) save();
})();
