/* LoxOS (Fork, docs/VISION.md): Bento-Seiten der Visu.

   Eine Bento-Seite (view.bento {cols, rows}, view.cells[], gebaut in bento.py)
   steht in #grid mit der Klasse "bento": ein festes Raster, jede Zelle mit
   Spalte, Zeile, Breite und Hoehe. Eine Zelle traegt Kacheln (items) oder ein
   Widget mit seinen Daten (inline, nicht ueber die Kanaele der Panes).

   Nichts wird hier nachgebaut, was es schon gibt: Kacheln kommen aus
   kachelHtml()/kachelBinden() (kachelfeld.js), Wetter und Kalender aus den
   Pane-Renderern mit frontData, Energie aus paintEnergy(), Verlauf, Werte und
   Kamera aus ihren Pane-Renderern mit den Daten der Zelle als Parameter. Nur
   der Spieler der Pane haengt an festen Element-IDs und kann je Seite einmal
   stehen - der Zellen-Spieler unten nutzt dieselben Helfer (sendCmd,
   nudgeSld, sldFill) fuer beliebig viele Zellen.

   Masse rechnet raster.js (bentoRaster, bentoMass, bentoStufe), damit Visu
   und Editor dasselbe Raster sehen. Jede Zelle bekommt ihre Pixelmasse als
   --bz-b/--bz-h und eine Groessenstufe (data-stufe): Inhalte skalieren mit
   der Zelle und zeigen in kleinen Zellen weniger, statt abgeschnitten zu
   werden (bento.css). */

// Aufbau einer Seite: Lage und Art jeder Zelle. Gleicher Aufbau -> updateBento
// zieht nur die Inhalte nach (Kamerabild und Webseite laufen weiter).
function bentoAufbau(v){
  return JSON.stringify([v.route, v.bento.cols, v.bento.rows,
    (v.cells||[]).map(c=>[c.x, c.y, c.w, c.h, c.widget||'', (c.items||[]).map(it=>it.id).join(',')])]);
}
// Nur diese eine Seite und keine Detailseite darueber: volle Flaeche ohne Leiste
function bentoVoll(){ return tabsCfg.length<=1 && stack.length<=1; }

function bentoMessen(g){
  const cs=getComputedStyle(g), px=v=>parseFloat(v)||0;
  return LoxRaster.bentoRaster(g.clientWidth, g.clientHeight, view.bento.cols, view.bento.rows,
                               px(cs.columnGap), px(cs.paddingLeft));
}

// ---- Stile der Panes fuer die Zellen ------------------------------------------
// Die Optik der Panes (Wetter, Energie, Verlauf, Kamera, Werte) haengt in
// grund.css und seiten.css an #frontpane. Statt sie zu kopieren, uebernimmt
// die Seite beim ersten Aufbau jede Regel fuer INHALTE der Pane mit
// ".grid.bento .bz-box" statt "#frontpane" - aendert Upstream die Optik, ziehen
// die Zellen mit. Aussen vor bleiben Regeln fuer den Pane-Kasten selbst (Lage
// im Bildschirm, Sichtbarkeit) und fuer Lagen, die eine Zelle nicht kennt
// (Split nebeneinander/uebereinander, Uhr-Seite, Verbindungsabbruch).
const BENTO_PANE_ZIEL='.grid.bento .bz-box';
const BENTO_PANE_OHNE=/\.split\b|\.hoch\b|\.saver\b|\.verbweg\b|\.sv-/;
function bentoSelektoren(liste){
  // an Kommas auf oberster Ebene trennen (:is(a,b) bleibt ganz)
  const teile=[]; let tiefe=0, anfang=0;
  for(let i=0; i<liste.length; i++){ const ch=liste[i];
    if(ch==='(') tiefe++; else if(ch===')') tiefe--;
    else if(ch===',' && tiefe===0){ teile.push(liste.slice(anfang, i)); anfang=i+1; } }
  teile.push(liste.slice(anfang));
  const raus=[];
  for(const roh of teile){ const s=roh.trim(), i=s.indexOf('#frontpane');
    if(i<0 || BENTO_PANE_OHNE.test(s)) continue;
    const rest=s.slice(i+'#frontpane'.length);
    if(!/\s|>|\+|~/.test(rest)) continue;   // Regel fuer den Kasten selbst, nicht fuer seinen Inhalt
    const vorn=s.slice(0, i).replace(/\.screen[\w.-]*\s*$/, '');
    raus.push(vorn+BENTO_PANE_ZIEL+rest);
  }
  return raus.join(', ');
}
function bentoRegeln(liste, raus){
  for(const r of liste){
    if(r.selectorText!==undefined){
      if(r.selectorText.indexOf('#frontpane')>=0){ const s=bentoSelektoren(r.selectorText);
        if(s) raus.push(s+'{'+r.style.cssText+'}'); }
    } else if(r.cssRules){   // @media, @supports, @layer: Inhalt im selben Rahmen
      const innen=[]; bentoRegeln(r.cssRules, innen);
      if(!innen.length) continue;
      const kopf=(r.media && r.media.mediaText!==undefined) ? '@media '+r.media.mediaText
               : (r.conditionText!==undefined) ? '@supports '+r.conditionText
               : (r.name!==undefined) ? '@layer '+r.name : null;
      if(kopf) raus.push(kopf+'{'+innen.join('\n')+'}');
    }
  }
}
function bentoPaneStile(){
  if(document.getElementById('bento-pane-stile')) return;
  const raus=[];
  for(const sh of document.styleSheets){
    if(!/\/panel\/(grund|seiten)\.css/.test(sh.href||'')) continue;
    let rs; try{ rs=sh.cssRules; }catch(e){ continue; }
    bentoRegeln(rs, raus);
  }
  const st=document.createElement('style'); st.id='bento-pane-stile'; st.textContent=raus.join('\n');
  document.head.appendChild(st);
}

function renderBento(){
  const g=el('grid'), sc=document.querySelector('.screen'); if(!g || !sc || !view || !view.bento) return;
  bentoPaneStile();
  stopVideo(); closeMenu(); setMore(null);
  g.classList.remove('panel','bigpage','anchorbot','scheme','list','fronttab','lx','hpages','punkte','fuss','haus','snapy');
  g.classList.add('bento');
  sc.classList.add('bento');
  sc.classList.toggle('bentovoll', bentoVoll());
  g.style.setProperty('--b-cols', view.bento.cols);
  g.style.setProperty('--b-rows', view.bento.rows);
  g.innerHTML='';
  renderTabs();   // Leiste (oder keine); applyPane meldet die Kanaele der Panes ab
  const br=bentoMessen(g);
  setzeFaktor(LoxRaster.kachelFaktorFuer(br.zw, br.zh));   // Kacheln wie im Raster: Faktor der Einheitszelle
  const zellen=view.cells||[];
  if(!zellen.length){
    g.innerHTML='<div class="bz-leer">Diese Seite hat noch keine Zellen. Im Konfigurator unter „Seiten“ '+
                'Widgets und Bausteine ins Raster ziehen.</div>';
  }
  for(const c of zellen){
    const z=document.createElement('div'), m=LoxRaster.bentoMass(br, c.w, c.h);
    z.className='bz';
    z.style.gridColumn=(c.x+1)+' / span '+c.w;
    z.style.gridRow=(c.y+1)+' / span '+c.h;
    z.style.setProperty('--bz-b', m.b.toFixed(1)+'px');
    z.style.setProperty('--bz-h', m.h.toFixed(1)+'px');
    z.dataset.stufe=LoxRaster.bentoStufe(m.b, m.h);
    const st=LoxRaster.bentoStufen(m.b, m.h); z.dataset.bstufe=st.b; z.dataset.hstufe=st.h;
    z.dataset.form=(m.h>m.b*1.15) ? 'hoch' : ((m.b>m.h*2.2) ? 'breit' : 'normal');
    g.appendChild(z);
    bentoFuellen(z, c);
  }
  g._bentoAufbau=bentoAufbau(view);
}

// Gleiche Seite, gleicher Aufbau: nur geaenderte Zellen neu fuellen.
// -> false, wenn sich der Aufbau geaendert hat (dann baut render() neu).
function updateBento(){
  const g=el('grid'); if(!g || !view || !view.bento || g._bentoAufbau!==bentoAufbau(view)) return false;
  const zs=[...g.querySelectorAll(':scope > .bz')], cells=view.cells||[];
  if(zs.length!==cells.length) return false;
  cells.forEach((c, i)=>{ const z=zs[i]; if(JSON.stringify(z._c)!==JSON.stringify(c)) bentoFuellen(z, c); });
  return true;
}

// Inhalt einer Zelle. Zelle und Daten bleiben am Knoten (z._c).
function bentoFuellen(z, c){
  z._c=c;
  if(c.items){ bentoKacheln(z, c); return; }
  const w=c.widget||'', art=w.split(':')[0];
  z.dataset.widget=art;
  if(c.fehler){ bentoHinweis(z, 'Inhalt nicht verfügbar'); return; }
  if(art==='clock') bentoUhrZelle(z);
  else if(art==='weather') renderWeatherPane(bentoBox(z));
  else if(art==='calendar') renderCalendarPane(bentoBox(z));
  else if(art==='energy'){
    if(!c.energy){ bentoHinweis(z, 'Energiefluss nicht gefunden'); return; }
    const b=bentoBox(z);
    let p=b.querySelector('.fp-page.epage');
    if(!p){ b.innerHTML='<div class="fp-page epage solo"></div>'; p=b.firstChild; }
    paintEnergy(p, c.energy);
  }
  else if(art==='chart') renderChartPane(bentoBox(z), c.chart||null);
  else if(art==='status'){
    const b=bentoBox(z);
    b.innerHTML='<div class="fp-page werte">'+svStatusZeilen(c.status||[])+'</div>';
    werteEinpassen(b);
  }
  else if(art==='camera'){
    if(!c.camera){ bentoHinweis(z, 'Kamera nicht gefunden'); return; }
    const b=bentoBox(z); b.classList.add('cam');
    renderCameraPane(b, {camera:c.camera, status:c.status});
  }
  else if(art==='player'){
    if(!c.player){ bentoHinweis(z, 'Audio-Zone nicht gefunden'); return; }
    bentoSpieler(z, c.player);
  }
  else if(art==='iframe') bentoWebseite(z, c);
}

// Fester Innenkasten einer Widget-Zelle: die Pane-Renderer zeichnen dort
// hinein wie in #frontpane und behalten ihren Zustand (Kamera, Verlauf).
function bentoBox(z){
  let b=z.querySelector(':scope > .bz-box');
  if(!b){ z.innerHTML='<div class="bz-box"></div>'; b=z.firstChild; }
  return b;
}
function bentoHinweis(z, text){
  z.innerHTML='<div class="bz-hinweis">'+esc(text)+'</div>';
}

// Kacheln: eine Kachel fuellt die Zelle (bis 2 x 2 wie im Raster), mehrere
// stehen untereinander als Zeilen.
function bentoKacheln(z, c){
  const its=c.items||[], n=its.length;
  const gr={w:Math.min(2, c.w), h:n===1 ? Math.min(2, c.h) : 1};
  z.classList.add('bz-kacheln');
  z.style.setProperty('--bz-n', n);
  z.innerHTML=its.map(it=>kachelHtml(it, gr, '', tileVarStyle(it))).join('');
  z.querySelectorAll(':scope > .tile[data-id]').forEach((t, i)=>{ t._it=its[i]; kachelBinden(t, its[i]); });
}

// ---- Uhr ----------------------------------------------------------------------
// Dieselbe Darstellung wie Kopfzeile und Uhr-Seite (tickClock), im selben Takt.
// Hohe Zellen stapeln Stunden und Minuten.
function bentoUhrZelle(z){
  if(!z.querySelector('.bz-uhr'))
    z.innerHTML='<div class="bz-uhr"><div class="bz-zeit"></div><div class="bz-datum"></div></div>';
  bentoUhr(new Date());
}
function bentoUhr(d){
  const uhren=document.querySelectorAll('#grid.bento .bz-uhr'); if(!uhren.length) return;
  const zeit=d.toLocaleTimeString(LANG, {hour:'2-digit', minute:'2-digit'});
  const datum=d.toLocaleDateString(LANG, {weekday:'long', day:'numeric', month:'long'});
  const teile=new Intl.DateTimeFormat(LANG, {hour:'2-digit', minute:'2-digit'}).formatToParts(d);
  const std=(teile.find(p=>p.type==='hour')||{}).value||'', min=(teile.find(p=>p.type==='minute')||{}).value||'';
  uhren.forEach(u=>{
    const hoch=u.closest('.bz').dataset.form==='hoch', z=u.querySelector('.bz-zeit');
    const schluessel=(hoch?'h':'q')+zeit;
    if(z.dataset.t!==schluessel){
      z.dataset.t=schluessel;
      z.innerHTML=hoch ? '<span>'+esc(std)+'</span><span class="bz-min">'+esc(min)+'</span>' : esc(zeit);
    }
    const dt=u.querySelector('.bz-datum'); if(dt.textContent!==datum) dt.textContent=datum;
  });
}

// Wetter und Kalender haengen an frontData: bei jedem {t:'front'} nachziehen.
function bentoFront(){
  document.querySelectorAll('#grid.bento > .bz[data-widget="weather"], #grid.bento > .bz[data-widget="calendar"]')
    .forEach(z=>bentoFuellen(z, z._c));
}

// ---- Audio --------------------------------------------------------------------
// Cover, Titel, Transport und Lautstaerke; dieselben Bloecke wie die Pane
// (player_blocks), PIN-Pflicht der Zone aus secured.
function bentoSpieler(z, p){
  const b=p.blocks||[], cover=b.find(x=>x.k==='cover'), title=b.find(x=>x.k==='title');
  const row=b.find(x=>x.k==='row'), sl=b.find(x=>x.k==='slider');
  z._sec=!!p.secured;
  let s=z.querySelector('.bz-spieler');
  if(!s){
    z.innerHTML='<div class="bz-spieler"><div class="bz-cover"><span class="coverph">'+svg(ICONS.music)+'</span><img alt=""></div>'+
      '<div class="bz-titel"><div class="bz-t1"></div><div class="bz-t2"></div></div>'+
      '<div class="bz-trans"></div>'+
      '<div class="bz-vol"><button type="button" class="sbtn" data-sd="dn" aria-label="Leiser">−</button>'+
      '<input type="range" class="sld" min="0" max="100" value="0" aria-label="Lautstärke">'+
      '<button type="button" class="sbtn" data-sd="up" aria-label="Lauter">+</button></div></div>';
    s=z.querySelector('.bz-spieler');
    const sld=s.querySelector('.sld'), zurueck=()=>bentoSpieler(z, z._c.player);
    s.querySelector('[data-sd="dn"]').addEventListener('pointerdown', ev=>{ ev.preventDefault(); nudgeSld(sld, -SLD_STEP, null, z._sec, zurueck); });
    s.querySelector('[data-sd="up"]').addEventListener('pointerdown', ev=>{ ev.preventDefault(); nudgeSld(sld, SLD_STEP, null, z._sec, zurueck); });
    sld.addEventListener('input', ()=>{ z._ziehen=true; sldFill(sld); });
    sld.addEventListener('change', ()=>{ z._ziehen=false;
      if(sld._uuid && sld._tmpl) sendCmd(sld._uuid, sld._tmpl.replace('{v}', sld.value), z._sec, {abbruch:zurueck}); });
  }
  const img=s.querySelector('.bz-cover img');
  if(cover && cover.src){ if(img.getAttribute('src')!==cover.src){
      img.onload=()=>img.style.opacity='1'; img.onerror=()=>img.style.opacity='0'; img.src=cover.src; } }
  else { img.removeAttribute('src'); img.style.opacity='0'; }
  s.querySelector('.bz-t1').textContent=title ? (title.text||'') : '';
  s.querySelector('.bz-t2').textContent=title ? (title.sub||'') : '';
  const tr=s.querySelector('.bz-trans'), cells=(row && row.cells)||[];
  if(tr.children.length!==cells.length){
    tr.innerHTML=cells.map((c, i)=>'<button type="button" class="btn'+(c.big?' big':'')+'" data-c="'+i+'"></button>').join('');
    tr.querySelectorAll('[data-c]').forEach(n=>n.addEventListener('pointerdown', ev=>{ ev.preventDefault();
      if(n._cmd) sendCmd(n._cmd.uuid, n._cmd.cmd, z._sec); }));
  }
  cells.forEach((c, i)=>{ const n=tr.querySelector('[data-c="'+i+'"]'); if(!n) return;
    n._cmd=c.cmd||null;
    n.innerHTML=c.icon ? svgF(ICONS[c.icon]||ICONS.info) : esc(c.label||'');
    n.setAttribute('aria-label', c.label||c.icon||'');
    n.className='btn'+(c.big?' big':''); });
  const sld=s.querySelector('.sld'), vol=s.querySelector('.bz-vol');
  vol.hidden=!sl;
  if(sl){ if(sl.cmd){ sld._uuid=sl.cmd.uuid; sld._tmpl=sl.cmd.tmpl; }
    if(!z._ziehen){ sld.value=sl.value; sldFill(sld); } }
}

// ---- Webseite (iframe) ------------------------------------------------------------
// Der Server prueft die Adresse (bento.py): "fehler" und "gesperrt" zeigen
// gleich die Fehlerzelle; sonst laedt der iframe, und laedt er nicht binnen
// ladenS Sekunden, zeigt die Zelle den Fehler mit dem Grund der Pruefung.
// sandbox: Skripte und eigene Herkunft (sonst laedt kaum eine Seite), Formulare
// (Anmeldung an Geraeten); keine Navigation der Visu, keine Popups.
const BENTO_SANDBOX='allow-scripts allow-same-origin allow-forms';
function bentoHost(url){ try{ return new URL(url).host; }catch(e){ return url; } }
function bentoWebFehler(grund, url){
  return '<div class="bz-wfehler">'+svg(ICONS.info)+'<b>'+esc(grund||'Seite lädt nicht')+'</b>'+
         '<span>'+esc(bentoHost(url))+'</span></div>';
}
function bentoWebseite(z, c){
  const pr=c.pruefung||{stand:'offen'};
  const kopf='<div class="bz-wkopf"><span class="bz-wname">'+esc(c.name||bentoHost(c.url))+'</span>'+
    (pr.stand==='eingeschraenkt' ? '<span class="bz-wwarn" title="'+esc(pr.grund||'')+'">'+svg(ICONS.info)+'</span>' : '')+'</div>';
  if(pr.stand==='fehler' || pr.stand==='gesperrt'){
    clearTimeout(z._wTimer); z._url=null;
    z.innerHTML='<div class="bz-web">'+kopf+bentoWebFehler(pr.grund, c.url)+'</div>';
    return;
  }
  if(z._url===c.url && z.querySelector('iframe')){
    const k=z.querySelector('.bz-wkopf'); if(k && k.outerHTML!==kopf) k.outerHTML=kopf;
    return;
  }
  z._url=c.url;
  z.innerHTML='<div class="bz-web">'+kopf+'<div class="bz-wrahmen"><iframe referrerpolicy="no-referrer"></iframe></div></div>';
  const f=z.querySelector('iframe');
  f.setAttribute('sandbox', BENTO_SANDBOX);
  f.title=c.name||bentoHost(c.url);
  let geladen=false;
  f.addEventListener('load', ()=>{ geladen=true; });
  clearTimeout(z._wTimer);
  z._wTimer=setTimeout(()=>{ if(geladen || z._url!==c.url) return;
    const r=z.querySelector('.bz-wrahmen'); if(r) r.innerHTML=bentoWebFehler(pr.grund, c.url); }, (c.ladenS||0)*1000);
  f.src=c.url;
}
