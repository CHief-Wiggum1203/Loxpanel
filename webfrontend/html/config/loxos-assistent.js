/* LoxOS (Fork, docs/VISION.md "LoxOS-Assistent"): "LoxOS-Streifen einrichten".

   Overlay #loxOv in fuenf Schritten nach dem Muster des Betriebsmodus-Assistenten
   (mzFlow() in geraete.js): Geraet, Anwesenheit, Aussehen, Startseite, Fertig.
   Rechts laeuft ab der Wahl des Geraets die echte Visu als Vorschau in seiner
   Groesse (/api/entwurf, wie "Gerät einrichten").

   Bis "Fertig" bleibt alles im Zustand LOX: PANELS, DEV und cur bleiben
   unberuehrt, Abbrechen aendert nichts (nur das Benennen eines Geraets in
   Schritt 1 gilt sofort, wie ueberall). "Fertig" legt eine NEUE Ansicht
   "LoxOS · <Geraet>" an (gibt es den Titel schon, wird durchgezaehlt, die
   Kennung folgt aus idAusName()), speichert sie, ordnet sie dem Geraet zu
   (ansichtAmGeraet: /api/panels, /api/device/switch), speichert Melder und
   Ruhe (/api/devices) und oeffnet den Bento-Editor der Seite. Betriebsmodi
   des Geraets bleiben, wie sie sind; Schritt 5 nennt sie.

   Laedt nach geraete.js (nameDevice, devSpeichern, devAusServer ...); das
   Overlay steht im Dokument hinter den Skripten, verdrahtet wird es darum
   erst in loxOpen(). */

const LOX_SET='edge';               // Kachel-Set des Streifens (theme_colors.KACHEL_SETS)
const LOX_TITEL='LoxOS · ';         // Titel der neuen Ansicht: davor der Geraetename
const LOX_VORSCHAU_MS=350;          // Entwurf erst nach dieser Pause schicken (wie geVorschau)
const LOX={step:0, device:'', vorschlag:null, presence:'', ruhe:true, ton:null, token:'', url:'', timer:0,
  benannt:'', _sig:'', _wired:false, _laeuft:false};
function loxFlow(){ return ['geraet','anwesenheit','aussehen','startseite','fertig']; }

// ---- Geraete ----------------------------------------------------------------------
function loxSchirm(n){ const s=DEVICE_SCREENS[n]; return (s && s.vw && s.vh) ? s : null; }
function loxStreifen(s){ const ab=META && META.streifenAb; return !!(s && ab && s.vw/s.vh>=ab); }
// Bekannte Geraete: Streifen oben, dann mit gemeldeter Groesse, unten ohne
function loxGeraete(){
  const rang=n=>{ const s=loxSchirm(n); return loxStreifen(s) ? 0 : (s ? 1 : 2); };
  return alleGeraeteNamen().map(n=>({name:n, rang:rang(n), schirm:loxSchirm(n)}))
    .sort((a,b)=>a.rang-b.rang || a.name.localeCompare(b.name));
}
function loxSig(){ return JSON.stringify([loxGeraete().map(g=>[g.name, g.rang]), ANON_DEVICES.map(anonKey)]); }
// Neue Geraete aus pollDevices: Schritt 1 nachziehen, ein gerade benanntes waehlen
function loxGeraeteNeu(){
  const ov=$('#loxOv'); if(!ov || ov.hidden || loxFlow()[LOX.step]!=='geraet') return;
  if(LOX.benannt && alleGeraeteNamen().indexOf(LOX.benannt)>=0){ loxGeraetWaehlen(LOX.benannt); LOX.benannt=''; }
  else if(loxSig()===LOX._sig) return;
  const b=$('#loxBody'); if(b && b.contains(document.activeElement) && document.activeElement.tagName==='INPUT') return;   // nicht beim Tippen
  loxRender();
}
function loxGeraetWaehlen(n){
  if(LOX.device===n) return;
  LOX.device=n; LOX.vorschlag=null;
  // Melder: der schon eingetragene, sonst keiner
  const p=(DEV[n]||{}).presence||'';
  LOX.presence=ACTIVE_OPTS.some(o=>o.uuid===p) ? p : '';
}
function loxModi(){ return ((DEV[LOX.device]||{}).modes||[]).filter(([m,p])=>m&&p); }

// ---- Die neue Ansicht -------------------------------------------------------------
function loxTitel(){
  const titel=new Set(Object.values(PANELS).map(p=>p && p.title));
  const t=LOX_TITEL+LOX.device; let k=t, n=2;
  while(titel.has(k)) k=t+' '+(n++);
  return k;
}
function loxId(){ return idAusName(loxTitel()); }
// Die Ansicht, die "Fertig" anlegt (UI-Form wie in PANELS); null ohne Vorschlag
function loxProfil(){
  const v=LOX.vorschlag; if(!v) return null;
  const ui={tileSet:LOX_SET}, s=kachelSetMeta(LOX_SET);
  if(LOX.ton!==null && s && s.farbton) ui[s.farbton.schluessel]=LOX.ton;   // "Original": kein Farbton
  return {title:loxTitel(), tabs:[pickKey(0)], rooms:[], cats:[], ui:ui,
    pickTabs:[JSON.parse(JSON.stringify(v.pickTab))], states:{}, tiles:{},
    device:{name:LOX.device, vw:v.format.vw, vh:v.format.vh}};
}
async function loxVorschlagHolen(){
  const n=LOX.device; if(!n || LOX.vorschlag) return;
  try{ const r=await fetch('/api/bento/vorschlag?device='+encodeURIComponent(n)); const j=await r.json();
    if(LOX.device===n && j && j.pickTab) LOX.vorschlag=j; }
  catch(e){ flash($('#loxToast'), T('Vorschlag nicht geladen:')+' '+e.message, false); }
}

// ---- Vorschau ---------------------------------------------------------------------
function loxVorschauMass(){
  const box=$('#loxVor'), f=$('#loxFrame'), v=LOX.vorschlag; if(!box||!f) return;
  const m=$('#loxVorMass');
  if(!v){ if(m) m.textContent=''; return; }
  const vw=v.format.vw, vh=v.format.vh;
  const s=Math.min(1, (box.clientWidth-16)/vw, (box.clientHeight-16)/vh);
  f.style.width=vw+'px'; f.style.height=vh+'px'; f.style.transform='scale('+s+')';
  f.style.left=Math.round((box.clientWidth-vw*s)/2)+'px'; f.style.top=Math.round((box.clientHeight-vh*s)/2)+'px';
  if(m) m.textContent=vw+' × '+vh+(s<1 ? ' · '+Math.round(s*100)+' %' : '');
}
function loxVorschau(){
  clearTimeout(LOX.timer);
  const h=$('#loxVorHinweis');
  if(!LOX.vorschlag){ if(h) h.textContent=T('Die Vorschau erscheint, sobald ein Gerät gewählt ist.'); return; }
  LOX.timer=setTimeout(async()=>{
    const p=loxProfil(), f=$('#loxFrame'); if(!p || !f) return;
    try{ const j=await postJson('/api/entwurf', {id:loxId(), panel:p, token:LOX.token});
      if(!j.ok || $('#loxOv').hidden) return;
      LOX.token=j.token;
      if(j.url!==LOX.url){ LOX.url=j.url; f.src=j.url; }
      if(h) h.textContent=(j.verworfen||[]).length ? T('Nicht übernommen:')+' '+j.verworfen.join('; ')
        : T('Die Vorschau ist die echte Visu in der Größe des Geräts.');
    }catch(e){ if(h) h.textContent=T('Vorschau nicht möglich:')+' '+e.message; }
  }, LOX_VORSCHAU_MS);
}

// ---- Schritte ---------------------------------------------------------------------
function loxGeraetHtml(){
  const l=loxGeraete();
  LOX._sig=loxSig();
  const karte=g=>{ const s=g.schirm;
    const was=s ? s.vw+'×'+s.vh+(g.rang===0 ? ' · '+T('Streifen') : ' · '+geraeteKlasse(s)) : T('Größe noch unbekannt');
    return '<div class="wzo'+(g.name===LOX.device?' on':'')+'" role="button" tabindex="0" data-lox-geraet="'+esc(g.name)+'">'+ikon('ext')+
      '<span class="tx"><b>'+esc(g.name)+'</b><span>'+esc(was)+'</span></span></div>'; };
  const anon=ANON_DEVICES.map(a=>'<div class="mzanon" data-lox-anon="'+esc(anonKey(a))+'" data-ip="'+esc(a.ip)+'" data-code="'+esc(a.code||'')+'">'+
    '<span class="agip">'+(a.code?('<b>'+T('Code')+' '+esc(a.code)+'</b> · '):'')+esc(a.ip)+(a.screen&&a.screen.vw?' · '+a.screen.vw+'×'+a.screen.vh:'')+'</span>'+
    '<input type="text" class="loxname" placeholder="'+T('Gerätename')+'">'+
    '<button class="wzbtn" data-lox-name>'+T('Namen vergeben')+'</button></div>').join('');
  return '<p class="wzq">'+T('Welches Gerät ist der Streifen?')+'</p>'+
    (l.length ? '<div class="wzopts">'+l.map(karte).join('')+'</div>'
      : (anon ? '' : '<div class="wznote">'+esc(T('Noch kein Gerät bekannt. Das Gerät muss die Visu einmal öffnen, etwa mit der LoxOS-Hülle.'))+'</div>'))+
    (anon ? '<div class="wznote" style="margin-top:10px">'+T('Verbunden, aber noch ohne Namen – erst benennen, dann auswählen:')+'</div>'+anon : '')+
    (LOX.benannt ? '<div class="wznote" style="margin-top:8px">'+esc(T('✓ Name vergeben – das Gerät verbindet sich neu und erscheint gleich oben:')+' '+LOX.benannt)+'</div>' : '')+
    '<div class="wznote" style="margin-top:10px">'+T('Streifen (Seitenverhältnis ab {a} : 1) stehen oben. Ein Gerät ohne gemeldete Größe bekommt das Format des Zielgeräts; der Bento-Editor warnt, wenn es anders meldet.').replace('{a}', fmtZahl((META&&META.streifenAb)||''))+'</div>';
}
function loxAnwesenheitHtml(){
  const opts=ACTIVE_OPTS.map(o=>'<option value="'+esc(o.uuid)+'"'+(o.uuid===LOX.presence?' selected':'')+'>'+
    esc((o.room?o.room+' · ':'')+o.name+' ('+o.type+')')+'</option>').join('');
  return '<p class="wzq">'+T('Wer sagt, ob jemand da ist?')+'</p>'+
    '<div class="wzfield"><label for="loxMelder">'+T('Präsenz- oder Bewegungsmelder')+'</label>'+
    '<select id="loxMelder"><option value="">'+T('— ohne Melder —')+'</option>'+opts+'</select></div>'+
    '<label class="chk" style="margin-top:12px"><input type="checkbox" id="loxRuhe"'+(LOX.ruhe?' checked':'')+(LOX.presence?'':' disabled')+'><span>'+
      T('Ruhe-Uhr statt Display aus')+'</span></label>'+
    '<div class="wznote" style="margin-top:10px">'+(LOX.presence
      ? T('Ist niemand da, zeigt der Streifen die Nacht-Uhr, das Display bleibt an.')
      : T('Ohne Melder geht das Display nach der Leerlaufzeit aus; die Ruhe-Uhr braucht einen Melder.'))+'</div>';
}
function loxAussehenHtml(){
  const s=kachelSetMeta(LOX_SET);
  const ton=(s && s.farbton) ? '<div class="lbl" style="margin-top:14px">'+T('Farbton')+'</div><div class="ks-schnell">'+
      '<button type="button" class="ks-ton'+(LOX.ton===null?' on':'')+'" data-lox-ton="" aria-pressed="'+(LOX.ton===null)+'">'+T('Original')+'</button>'+
      s.farbton.auswahl.map(f=>'<button type="button" class="ks-ton'+(f.wert===LOX.ton?' on':'')+'" data-lox-ton="'+f.wert+'" aria-pressed="'+(f.wert===LOX.ton)+'">'+
        '<span class="ks-punkt" style="background:'+esc(f.farbe)+'"></span>'+esc(T(f.label))+'</button>').join('')+'</div>' : '';
  return '<p class="wzq">'+T('Wie soll es aussehen?')+'</p>'+
    '<div class="wznote">'+T('Kachel-Set')+': <b>'+esc(s ? T(s.label) : LOX_SET)+'</b>'+(s && s.info ? ' – '+esc(T(s.info)) : '')+'</div>'+ton+
    '<div class="wznote" style="margin-top:10px">'+T('Weiteres unter Ansichten → Aussehen.')+'</div>';
}
// Was eine Zelle zeigt: Widget (Name aus dem Bento-Editor) oder die Bausteine
function loxZelle(c){
  if(c.widget){ const k=c.widget.split(':')[0], w=BE_WIDGETS.find(x=>x[0]===k), u=c.widget.slice(k.length+1);
    const q=u ? (META.controls||[]).find(x=>x.uuid===u) : null;
    return T(w ? w[1] : k)+(q ? ' · '+q.name : ''); }
  return (c.ids||[]).map(u=>((META.controls||[]).find(x=>x.uuid===u)||{name:u}).name).join(', ');
}
function loxStartseiteHtml(){
  const v=LOX.vorschlag;
  if(!v) return '<p class="wzq">'+T('Startseite')+'</p><div class="wznote">'+T('Der Vorschlag lädt …')+'</div>';
  const b=v.pickTab.bento;
  return '<p class="wzq">'+T('Die Startseite')+'</p>'+
    '<div class="wznote">'+T('Eine Bento-Seite mit {s} × {z} Feldern, gebaut für {w} × {h}.').replace('{s}', b.cols).replace('{z}', b.rows)
      .replace('{w}', v.format.vw).replace('{h}', v.format.vh)+(v.formatBekannt ? '' : ' '+T('Größe noch unbekannt – das Format des Zielgeräts.'))+'</div>'+
    '<ul class="lox-zellen">'+b.cells.map(c=>'<li><b>'+esc(loxZelle(c))+'</b> <span>'+c.w+' × '+c.h+'</span></li>').join('')+'</ul>'+
    '<div class="wznote" style="margin-top:10px">'+T('Anpassen danach im Bento-Editor; er steht nach „Fertig“ offen.')+'</div>';
}
function loxFertigHtml(){
  const g=LOX.device, modi=loxModi(), s=kachelSetMeta(LOX_SET);
  const ton=(LOX.ton===null || !s || !s.farbton) ? T('Original') : T((s.farbton.auswahl.find(f=>f.wert===LOX.ton)||{label:String(LOX.ton)}).label);
  const melder=LOX.presence ? presenceName(LOX.presence)+(LOX.ruhe ? ' · '+T('Ruhe-Uhr') : '') : T('ohne Melder');
  const zeile=(k,w)=>'<div class="mzrow"><span class="mzml">'+esc(k)+'</span><b>'+esc(w)+'</b></div>';
  return '<p class="wzq">'+T('Fertig – das wird angelegt')+'</p><div class="mztable">'+
      zeile(T('Neue Ansicht'), loxTitel()+' (?panel='+loxId()+')')+zeile(T('Gerät'), g)+zeile(T('Anwesenheit'), melder)+
      zeile(T('Aussehen'), (s ? T(s.label) : LOX_SET)+' · '+ton)+zeile(T('Startseite'), T('eine Bento-Seite, keine Leiste'))+'</div>'+
    (modi.length ? '<div class="wznote lox-modi" style="margin-top:12px">'+esc(T('{g} hat Betriebsmodi ({m}): Schaltet Loxone den Modus um, kann das Gerät auf eine andere Ansicht wechseln. Sie bleiben, wie sie sind; ändern unter Geräte → {g} → Betriebsmodi.')
      .split('{g}').join(g).replace('{m}', modi.map(([m,p])=>m+' → '+ansichtName(p)).join(', ')))+'</div>' : '')+
    '<div class="wznote" style="margin-top:10px">'+T('Bestehende Ansichten bleiben unverändert. Weitere Seiten legst du danach im Seiten-Editor an.')+'</div>';
}

function loxRender(){
  const f=loxFlow(), key=f[LOX.step], b=$('#loxBody');
  $('#loxStep').textContent=T('Schritt')+' '+(LOX.step+1)+' / '+f.length;
  $('#loxKopf').textContent=LOX.device ? LOX.device : '';
  b.innerHTML=key==='geraet' ? loxGeraetHtml() : key==='anwesenheit' ? loxAnwesenheitHtml()
    : key==='aussehen' ? loxAussehenHtml() : key==='startseite' ? loxStartseiteHtml() : loxFertigHtml();
  b.querySelectorAll('[data-lox-geraet]').forEach(el=>{
    el.onclick=()=>{ loxGeraetWaehlen(el.dataset.loxGeraet); loxRender(); };
    el.onkeydown=e=>{ if((e.key==='Enter'||e.key===' ') && e.target===el){ e.preventDefault(); el.click(); } }; });
  b.querySelectorAll('[data-lox-anon]').forEach(row=>{
    const inp=row.querySelector('.loxname'), btn=row.querySelector('[data-lox-name]');
    const go=async()=>{ const name=inp.value.trim(); if(!name){ inp.focus(); return; }
      btn.disabled=true;
      if(await nameDevice(row.dataset.ip, name, row.dataset.code)){ LOX.benannt=name; loxRender(); } else btn.disabled=false; };
    btn.onclick=go; inp.onkeydown=e=>{ if(e.key==='Enter'){ e.preventDefault(); go(); } }; });
  { const m=$('#loxMelder'), r=$('#loxRuhe');
    if(m) m.onchange=()=>{ LOX.presence=m.value; loxRender(); };
    if(r) r.onchange=()=>{ LOX.ruhe=r.checked; }; }
  b.querySelectorAll('[data-lox-ton]').forEach(el=>{ el.onclick=()=>{
    LOX.ton=el.dataset.loxTon==='' ? null : Number(el.dataset.loxTon); loxRender(); loxVorschau(); }; });
  $('#loxBack').disabled=LOX.step===0 || LOX._laeuft;
  const letzt=LOX.step===f.length-1;
  $('#loxNext').textContent=letzt ? T('Fertig – auf {g} anzeigen').replace('{g}', LOX.device) : T('Weiter →');
  $('#loxNext').disabled=LOX._laeuft || (key==='geraet' && !LOX.device) || (key!=='geraet' && !LOX.vorschlag);
  loxVorschauMass();
}
async function loxNext(){
  const f=loxFlow();
  if(LOX.step<f.length-1){
    if(f[LOX.step]==='geraet'){ $('#loxNext').disabled=true; await loxVorschlagHolen(); if(!LOX.vorschlag){ loxRender(); return; } }
    LOX.step++; loxRender(); loxVorschau(); return;
  }
  await loxFertig();
}

// ---- Oeffnen, Schliessen, Fertig ----------------------------------------------------
function loxOpen(){
  // ohne Struktur beginnt der Weg beim Miniserver (wie geOpen)
  if(EINR){ setRubric('settings'); flash($('#toast'), T('Erst den Miniserver verbinden'), false); return; }
  if(!LOX._wired){ LOX._wired=true;
    $('#loxOv').onclick=e=>{ if(e.target===$('#loxOv')) loxClose(); };
    $('#loxX').onclick=loxClose; $('#loxAbbrechen').onclick=loxClose;
    $('#loxBack').onclick=()=>{ if(LOX.step>0 && !LOX._laeuft){ LOX.step--; loxRender(); } };
    $('#loxNext').onclick=loxNext;
    window.addEventListener('resize', ()=>{ if(!$('#loxOv').hidden) loxVorschauMass(); });
  }
  Object.assign(LOX, {step:0, device:'', vorschlag:null, presence:'', ruhe:true, ton:null, token:'', url:'', benannt:'', _laeuft:false});
  $('#loxOv').hidden=false; loxRender(); loxVorschau();
}
// Schliessen ersetzt den iframe (wie geClose): die Visu darin bliebe sonst als
// Verbindung ohne Namen stehen
function loxClose(){
  clearTimeout(LOX.timer); LOX.url='';
  const f=$('#loxFrame'), n=document.createElement('iframe'); n.id='loxFrame'; n.title=f.title; f.replaceWith(n);
  $('#loxOv').hidden=true;
}
// Geraeteliste fuer /api/devices: der gespeicherte Stand (offene Aenderungen an
// anderen Geraeten gehen nicht nebenbei mit), dazu jede Zuordnung, die der
// Server kennt (ein Geraet nur mit Zuordnung fehlt in GER_GESPEICHERT und ginge
// sonst verloren), und fuer dieses Geraet Zuordnung, Melder und Ruhe.
function loxGeraeteListe(name, id){
  const liste=JSON.parse(JSON.stringify(GER_GESPEICHERT||{}));
  Object.entries(DEVICE_ZUORDNUNG).forEach(([n,z])=>{ if(z && !liste[n]) liste[n]={auto:true, modes:{}, panel:z}; });
  const d=liste[name]||(liste[name]={auto:true, modes:{}});
  d.panel=id;
  if(LOX.presence) d.presence=LOX.presence; else delete d.presence;
  if(LOX.presence && LOX.ruhe) d.ruhe=true; else delete d.ruhe;
  return liste;
}
async function loxFertig(){
  const p=loxProfil(); if(!p || LOX._laeuft) return;
  LOX._laeuft=true; $('#loxNext').disabled=true; $('#loxBack').disabled=true;
  const id=loxId(), name=LOX.device;
  try{
    PANELS[id]=p; cur=id; tileSel=null; curPickIdx=0; renderList(); markDirty();
    loxClose();
    await ansichtAmGeraet(id, name, true, 0);   // speichert die Ansicht und ordnet sie zu
    if(!GESPEICHERT[id]) return;                // Speichern gescheitert: die Leiste meldet es
    const j=await devSpeichern(loxGeraeteListe(name, id));
    if(j.ok){ if(!OFFEN.has('geraete')) DEV=devAusServer(j.devices); renderDevices(); }
    else flash($('#toast'), T('Geräte')+': '+(j.error||T('Fehler')), false);
    // der Bento-Editor der neuen Seite
    subMerken('pconf','seiten'); setRubric('pconf'); renderSubtabs(); showSub('seiten');
  }catch(e){ flash($('#toast'), 'Fehler: '+e, false); }
  finally{ LOX._laeuft=false; }
}
['#loxOpenBtn','#ovLoxOS'].forEach(sel=>{ const k=$(sel); if(k) k.onclick=loxOpen; });
document.addEventListener('keydown', e=>{ if(e.key==='Escape' && $('#loxOv') && !$('#loxOv').hidden) loxClose(); });
