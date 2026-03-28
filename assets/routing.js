(function(){
function resolveDoc(){
  var list=[];
  try{list.push(window.parent);}catch(e1){}
  try{list.push(window.top);}catch(e2){}
  list.push(window);
  for(var i=0;i<list.length;i++){
    try{
      var d=list[i].document;
      if(!d)continue;
      var sb=d.querySelector('section[data-testid="stSidebar"]')||d.querySelector('[data-testid="stSidebar"]');
      var nav=d.querySelector('nav.sticky-nav');
      if(sb&&nav)return d;
    }catch(e3){}
  }
  for(var j=0;j<list.length;j++){
    try{
      var d2=list[j].document;
      if(d2&&(d2.querySelector('section[data-testid="stSidebar"]')||d2.querySelector('[data-testid="stSidebar"]')))return d2;
    }catch(e4){}
  }
  try{return window.parent.document;}catch(e5){return document;}
}
var pd=resolveDoc();
var pw=pd.defaultView||window;
if(pw.__cfSidebarToggleInit)return;
pw.__cfSidebarToggleInit=true;
var legacy=pd.getElementById('sob-host');
if(legacy)try{legacy.remove()}catch(e0){}
var oldFab=pd.getElementById('sob');
if(oldFab&&!oldFab.hasAttribute('data-cf-hamburger'))try{oldFab.remove()}catch(e1){}
var sOpen=true;
function sbEl(){return pd.querySelector('section[data-testid="stSidebar"]')||pd.querySelector('[data-testid="stSidebar"]')}
function iso(){return sOpen}
function applyClosed(sb){
  if(!sb)return;
  sb.setAttribute('aria-expanded','false');
  sb.style.setProperty('display','none','important');
  sb.style.setProperty('visibility','hidden','important');
  sb.style.setProperty('opacity','0','important');
  sb.style.setProperty('min-width','0','important');
  sb.style.setProperty('max-width','0','important');
  sb.style.setProperty('width','0','important');
  sb.style.setProperty('overflow','hidden','important');
  sb.style.setProperty('transform','translateX(-100%)','important');
  sb.style.setProperty('pointer-events','none','important');
}
function applyOpen(sb){
  if(!sb)return;
  sb.setAttribute('aria-expanded','true');
  sb.style.setProperty('display','flex','important');
  sb.style.setProperty('visibility','visible','important');
  sb.style.setProperty('opacity','1','important');
  sb.style.setProperty('width','21rem','important');
  sb.style.setProperty('min-width','21rem','important');
  sb.style.setProperty('max-width','','important');
  sb.style.setProperty('transform','none','important');
  sb.style.setProperty('position','relative','important');
  sb.style.removeProperty('overflow');
  sb.style.removeProperty('pointer-events');
}
function opn(){var sb=sbEl();if(sb){sOpen=true;applyOpen(sb);}}
function cls(){
  var sb=sbEl();
  if(sb){
    sOpen=false;
    applyClosed(sb);
    queueMicrotask(function(){if(!sOpen)applyClosed(sbEl());});
    setTimeout(function(){if(!sOpen)applyClosed(sbEl());},0);
    setTimeout(function(){if(!sOpen)applyClosed(sbEl());},50);
  }
}
function toggleFromUi(ev){
  if(ev){ev.preventDefault();ev.stopPropagation();}
  if(iso())cls();else opn();
}
function onDocClick(ev){
  var el=ev.target;
  if(el&&el.nodeType===3)el=el.parentElement;
  if(!el||!el.closest)return;
  if(!el.closest('[data-cf-hamburger="1"]'))return;
  toggleFromUi(ev);
}
pd.addEventListener('click',onDocClick,false);
/* Sticky nav: anchors inside inactive st.tabs are not mounted — switch tab first, then scroll. */
function cfFindMainDashTabButtons(){
  var lists=pd.querySelectorAll('[data-baseweb="tab-list"]');
  for(var i=0;i<lists.length;i++){
    var tabs=lists[i].querySelectorAll('[role="tab"]');
    if(tabs.length!==3)continue;
    var a=(tabs[0].textContent||'').trim();
    var b=(tabs[1].textContent||'').trim();
    if(a.indexOf('Setup')>=0&&b.indexOf('Cashflow')>=0)return tabs;
  }
  return null;
}
function cfClickMainDashTab(idx,cb,retries){
  retries=retries||0;
  var tabs=cfFindMainDashTabButtons();
  if(!tabs||!tabs[idx]){
    if(retries<30){setTimeout(function(){cfClickMainDashTab(idx,cb,retries+1);},120);return;}
    if(cb)cb();
    return;
  }
  try{tabs[idx].click();}catch(e1){}
  setTimeout(function(){if(cb)cb();},480);
}
function cfOpenQuickReference(){
  var exps=pd.querySelectorAll('[data-testid="stExpander"]');
  for(var i=0;i<exps.length;i++){
    var sum=exps[i].querySelector('summary');
    if(!sum)continue;
    var tx=(sum.textContent||'').replace(/\s+/g,' ').trim();
    if(tx.indexOf('Quick Reference')<0)continue;
    var det=exps[i].querySelector('details');
    if(det&&!det.open)try{sum.click();}catch(e){}
    break;
  }
}
function cfScrollToHashId(id){
  var n=0;
  function one(){
    var el=pd.getElementById(id);
    if(el){
      el.scrollIntoView({behavior:'smooth',block:'start'});
      try{pw.history.replaceState(null,'','#'+id);}catch(e){}
      return;
    }
    n++; if(n<50)setTimeout(one,110);
  }
  setTimeout(one,60);
}
function cfOnStickyNavClick(ev){
  var t=ev.target;
  if(t&&t.nodeType===3)t=t.parentElement;
  if(!t||!t.closest)return;
  var a=t.closest('a[href^="#"]');
  if(!a||!a.closest('.sticky-nav'))return;
  var href=a.getAttribute('href')||'';
  var id=href.slice(1);
  if(!id)return;
  var map={setup:0,'quant-dashboard':0,strategies:1,risk:2,scanner:2,news:2,guide:2};
  if(map[id]===undefined)return;
  ev.preventDefault();
  ev.stopPropagation();
  var tidx=map[id];
  cfClickMainDashTab(tidx,function(){
    if(id==='guide'){
      setTimeout(function(){
        cfOpenQuickReference();
        setTimeout(function(){cfScrollToHashId(id);},380);
      },120);
    }else{
      cfScrollToHashId(id);
    }
  });
}
pd.addEventListener('click',cfOnStickyNavClick,true);
function ensureToggle(){
  var fab=pd.getElementById('sob');
  if(!fab){
    fab=pd.createElement('button');
    fab.type='button';fab.id='sob';fab.className='cf-vip-fab';
    fab.setAttribute('data-cf-hamburger','1');fab.setAttribute('aria-label','Open or close settings');
    fab.textContent='\u2630';pd.body.appendChild(fab);
  }else if(!fab.getAttribute('data-cf-hamburger'))fab.setAttribute('data-cf-hamburger','1');
}
function syncToggleUi(){
  ensureToggle();
  if(!sOpen)applyClosed(sbEl());
  var t=pd.getElementById('sob')||pd.querySelector('[data-cf-hamburger="1"]');
  if(!t)return;
  t.textContent=iso()?'\u2715':'\u2630';
  t.title=iso()?'Close settings':'Open settings';
  t.setAttribute('aria-expanded',iso()?'true':'false');
}
function armSidebarMo(){
  var sb=sbEl();
  if(!sb||sb.__cfMo)return;
  sb.__cfMo=1;
  new MutationObserver(function(){
    if(!sOpen){
      var x=sbEl();
      if(x)applyClosed(x);
    }
  }).observe(sb,{attributes:true,attributeFilter:['style','class']});
}
function hideDefaultStreamlitHeader(){
  var all=pd.querySelectorAll('header,[data-testid*="eader"],[data-testid*="Header"]');
  for(var i=0;i<all.length;i++){
    all[i].style.setProperty('display','none','important');
  }
}
ensureToggle();
armSidebarMo();
setInterval(function(){ensureToggle();armSidebarMo();syncToggleUi();},400);
hideDefaultStreamlitHeader();setInterval(hideDefaultStreamlitHeader,1500);
})();