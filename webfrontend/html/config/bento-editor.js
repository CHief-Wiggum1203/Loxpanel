/* LoxOS (Fork, docs/VISION.md): Seiten-Editor fuer Bento-Seiten.

   Haengt am Seiten-Editor (seiten-editor.js): Ist der Seiteninhalt "Bento",
   zeichnet beZeichnen() statt Palette, Flaeche und Liste den Bento-Editor.
   Gearbeitet wird direkt auf pickTabs[i].bento ({cols, rows, format,
   cells[]}, Format in VISION.md); jede Aenderung meldet ctx.geaendert(), die
   Live-Vorschau in der echten Visu zieht nach.

   Grenzen und Standards kommen vom Server (META.bento, bento_format.py),
   Rasterrechnung und Kollision aus raster.js - dieselben wie in der Visu.
   Die Flaeche zeigt das gewaehlte Vorschaugeraet: ohne weitere Seiten die
   volle Flaeche, sonst abzueglich der Leiste des Kachel-Sets (leisteMasse).

   Bedienung: Widget oder Baustein antippen legt eine Zelle auf dem ersten
   freien Feld an. Ziehen verschiebt, der Griff unten rechts aendert die
   Groesse; besetzte Felder nehmen nichts an. Tastatur: Pfeile verschieben,
   Umschalt + Pfeil aendert die Groesse, Entf nimmt die Zelle von der Seite. */

const BE_WIDGETS=[['clock','Uhr'],['weather','Wetter'],['calendar','Kalender'],['player','Audio'],
  ['energy','Energiefluss'],['camera','Kamera'],['chart','Verlauf'],['status','Werte'],['iframe','Webseite'],
  ['ansicht','Raum-Display']];
// Ohne Quelle: einmal je Seite (wie bento_format.py)
const BE_EINZELN=['clock','weather','calendar'];
// Seitenverhaeltnis von Seite und Vorschaugeraet: mehr Abweichung -> Warnung
const BE_FORMAT_TOLERANZ=0.1;
const BE_ZUSTAND={};   // je Seite (ctx.key): gewaehlte Zelle, Meldung
let BE_ZIEHEN=null;    // laufendes Ziehen oder Groesse aendern

function beGrenzen(){ return (META && META.bento) || null; }
function beZustand(ctx){ return BE_ZUSTAND[ctx.key]||(BE_ZUSTAND[ctx.key]={sel:null, meldung:'', urlFehler:false}); }

// Seiteninhalt auf "Bento" stellen: ein leeres Raster im Standard des Servers,
// gebaut fuer das Vorschaugeraet. Ein Widget der Seite gilt dann nicht mehr.
function beAnlegen(ctx){
  const e=ctx.seite(), gr=beGrenzen(); if(!gr) return;
  delete e.widget;
  if(!e.bento){
    e.bento={cols:gr.spaltenStandard, rows:gr.zeilenStandard, cells:[]};
    const g=ctx.geraet(); if(g && g.vw && g.vh) e.bento.format={vw:g.vw, vh:g.vh};
  }
}

// ---- Rechnung ----------------------------------------------------------------------
function beFlaeche(ctx){
  const g=ctx.geraet(), b=ctx.seite().bento, p=ctx.panel;
  const voll=((p && p.tabs)||[]).length<=1;   // wie die Visu: nur diese Seite -> keine Leiste
  const lm=leisteMasse(ctx.ui().tileSet, g.vw, g.vh);
  const x0=voll ? 0 : lm.railW+lm.rahmenX/2, y0=(!voll && lm.art==='oben') ? lm.tabsH : 0;
  const w=g.vw-(voll ? 0 : lm.railW+lm.rahmenX), h=g.vh-(voll ? 0 : lm.tabsH+lm.rahmenY);
  return {g, voll, lm, x0, y0, w, h, br:LoxRaster.bentoRaster(w, h, b.cols, b.rows, lm.gap, lm.pad)};
}
function beOrt(f, c){
  const m=LoxRaster.bentoMass(f.br, c.w, c.h);
  return {x:f.x0+f.br.innen+c.x*(f.br.zw+f.br.abstand), y:f.y0+f.br.innen+c.y*(f.br.zh+f.br.abstand), w:m.b, h:m.h};
}
function beKasten(f, c){ const o=beOrt(f, c);
  return 'left:'+sePct(o.x, f.g.vw)+';top:'+sePct(o.y, f.g.vh)+';width:'+sePct(o.w, f.g.vw)+';height:'+sePct(o.h, f.g.vh); }
// Feld (Spalte, Zeile) unter einem Punkt der Flaeche (in Geraete-Pixeln)
function beFeld(f, px, py){
  const s=Math.floor((px-f.x0-f.br.innen+f.br.abstand/2)/(f.br.zw+f.br.abstand));
  const z=Math.floor((py-f.y0-f.br.innen+f.br.abstand/2)/(f.br.zh+f.br.abstand));
  return {x:Math.max(0, Math.min(f.br.cols-1, s)), y:Math.max(0, Math.min(f.br.rows-1, z))};
}
// Erstes freies Feld fuer eine Zelle w x h, sonst null
function bePlatz(b, w, h){
  for(let y=0; y+h<=b.rows; y++) for(let x=0; x+w<=b.cols; x++)
    if(LoxRaster.bentoFrei(b.cells, b.cols, b.rows, {x, y, w, h}, -1)) return {x, y, w, h};
  return null;
}
// Adresse einer Webseite: dieselbe Regel wie _clean_iframe_url (bento_format.py)
function beUrlOk(u){
  const gr=beGrenzen(); if(typeof u!=='string' || !gr) return false;
  u=u.trim();
  if(!u || u.length>gr.urlMax || /[\s\x00-\x1f\x7f]/.test(u) || !/^https?:\/\/[^/?#]/i.test(u)) return false;
  let t; try{ t=new URL(u); }catch(e){ return false; }
  return (t.protocol==='http:' || t.protocol==='https:') && !!t.hostname && !t.username && !t.password;
}
// Raum-Display: Ansichten, die eine Zelle zeigen kann - alle ausser der, die
// gerade bearbeitet wird (sie zeigte sich sonst in sich selbst, bento.py)
function beAnsichten(ctx){ return Object.keys(PANELS).filter(id=>id!=='__global__' && PANELS[id]!==ctx.panel); }
function beAnsichtOptionen(arg, ctx){
  const ids=beAnsichten(ctx);
  return (arg && ids.indexOf(arg)<0 ? '<option value="'+esc(arg)+'" selected>'+esc(arg+' – '+T('Ansicht nicht gefunden'))+'</option>' : '')+
    ids.map(id=>'<option value="'+esc(id)+'"'+(id===arg ? ' selected' : '')+'>'+esc(ansichtName(id))+'</option>').join('');
}
// Format der Zelle: der Bildschirm des Zielgeraets der Ansicht (wie bento.py)
function beAnsichtFormat(arg){
  const d=(PANELS[arg]||{}).device||{};
  return (d.vw && d.vh)
    ? '<p class="hint">'+esc(T('Gebaut für')+' '+(d.name ? d.name+' · ' : '')+d.vw+' × '+d.vh)+' – '+T('die Zelle zeigt sie in dieser Form.')+'</p>'
    : '<p class="hint">'+T('Die Ansicht kennt kein Zielgerät mit Größe und füllt deshalb die Zelle. Legt „Gerät einrichten“ eine Ansicht für ein Display an, merkt sie sich dessen Größe.')+'</p>';
}
// Bausteine der Seite ohne Zelle
function beOffen(e){ const drin=new Set(e.bento.cells.flatMap(c=>c.ids||[])); return (e.picks||[]).filter(u=>!drin.has(u)); }

function beName(c){
  if(c.ids) return c.ids.map(u=>{ const k=seCtrl(u); return k ? k.name : u; }).join(', ');
  const art=wKind(c.widget||''), arg=wArg(c.widget||''), n=T((BE_WIDGETS.find(x=>x[0]===art)||[art, art])[1]);
  if(art==='iframe') return n+(c.name ? ' · '+c.name : (c.url ? ' · '+c.url : ''));
  if(art==='ansicht') return n+(arg ? ' · '+ansichtName(arg) : '');
  if(art==='player' || art==='energy' || art==='camera'){ const k=seCtrl(arg.split('|')[0]); return n+(k ? ' · '+k.name : ''); }
  if(art==='chart' || art==='status'){ const uu=arg.split(',').filter(Boolean); return n+(uu.length ? ' · '+uu.length : ''); }
  return n;
}

// ---- Zeichnen ----------------------------------------------------------------------
// -> true, wenn die Seite eine Bento-Seite ist und der Editor sie gezeichnet hat
function beZeichnen(host){
  const ctx=host._se, e=ctx && ctx.seite ? ctx.seite() : null;
  const sp=host.querySelector('.se-spalten');
  let box=host.querySelector('[data-be]');
  // Die Klasse setzt display:grid und schlaegt das hidden-Attribut - darum ueber den Stil
  if(!e || !e.bento || !beGrenzen()){ if(box) box.remove(); if(sp) sp.style.display=''; return false; }
  if(!box){ box=document.createElement('div'); box.setAttribute('data-be', ''); box.className='be';
    sp.parentNode.insertBefore(box, sp); beBinden(box, host); }
  sp.style.display='none';
  host.querySelector('[data-se-leiste]').innerHTML=seLeisteHtml(ctx);
  host.querySelector('[data-se-kopf]').innerHTML=seKopfHtml(ctx, {pg:{widget:'bento'}});   // nur die Geraetewahl
  box.innerHTML=beHtml(ctx);
  if(window.I18N && I18N.applyChrome) I18N.applyChrome(box);
  return true;
}
function beZahlHtml(k, n, wert, lo, hi){
  return '<div class="field"><label class="lbl" for="be-'+k+'">'+T(n)+'</label><input type="number" id="be-'+k+'" data-be-raster="'+k+
    '" min="'+lo+'" max="'+hi+'" value="'+wert+'"></div>';
}
function beFormatHtml(b, f){
  const g=f.g, fm=b.format;
  if(!fm) return '<span class="hint">'+T('Kein Format gespeichert.')+'</span> <button type="button" class="minibtn" data-be-format>'+T('Format übernehmen')+'</button>';
  const passt=Math.abs((fm.vw/fm.vh)/(g.vw/g.vh)-1)<=BE_FORMAT_TOLERANZ;
  return '<span class="'+(passt ? 'be-ok' : 'be-warn')+'">'+esc(T('Gebaut für')+' '+fm.vw+' × '+fm.vh)+' · '+
    T(passt ? 'Vorschaugerät passt' : 'anderes Seitenverhältnis als das Vorschaugerät')+'</span>'+
    (passt ? '' : ' <button type="button" class="minibtn" data-be-format>'+T('Format übernehmen')+'</button>');
}
function beHtml(ctx){
  const e=ctx.seite(), b=e.bento, gr=beGrenzen(), f=beFlaeche(ctx), st=beZustand(ctx);
  if(st.sel!=null && !b.cells[st.sel]) st.sel=null;
  let h='<div class="be-kopf">'+beZahlHtml('cols', 'Spalten', b.cols, gr.spaltenMin, gr.spaltenMax)+
    beZahlHtml('rows', 'Zeilen', b.rows, gr.zeilenMin, gr.zeilenMax)+'<div class="be-format">'+beFormatHtml(b, f)+'</div></div>';
  h+='<div class="be-flaeche" data-be-flaeche style="aspect-ratio:'+f.g.vw+' / '+f.g.vh+'">';
  if(!f.voll){
    const lm=f.lm, t=lm.railW ? {x:0, y:0, w:lm.railW, h:f.g.vh}
      : {x:lm.rahmenX/2, y:lm.art==='oben' ? 0 : f.g.vh-lm.tabsH, w:f.g.vw-lm.rahmenX, h:lm.tabsH};
    h+='<div class="be-leiste" style="'+seKasten(t, f.g)+'"></div>';
  }
  for(let y=0; y<b.rows; y++) for(let x=0; x<b.cols; x++)
    if(LoxRaster.bentoFrei(b.cells, b.cols, b.rows, {x, y, w:1, h:1}, -1))
      h+='<div class="be-frei" data-be-feld="'+x+','+y+'" style="'+beKasten(f, {x, y, w:1, h:1})+'"></div>';
  b.cells.forEach((c, i)=>{
    const fehlt=c.widget==='iframe' && !beUrlOk(c.url||'');
    h+='<div class="be-z'+(i===st.sel ? ' sel' : '')+(c.ids ? ' kacheln' : '')+(fehlt ? ' fehlt' : '')+'" tabindex="0" role="button" data-be-z="'+i+
      '" aria-label="'+esc(beName(c)+', '+c.w+' × '+c.h)+'" style="'+beKasten(f, c)+'">'+
      '<span class="be-zn">'+esc(beName(c))+'</span><span class="be-zg">'+c.w+' × '+c.h+'</span>'+
      (fehlt ? '<span class="be-zf">'+T('Adresse fehlt')+'</span>' : '')+
      (i===st.sel ? '<span class="be-griff" data-be-griff="'+i+'" aria-hidden="true"></span>' : '')+'</div>';
  });
  h+='</div>';
  h+='<p class="hint">'+T('Widget oder Baustein antippen legt eine Zelle auf dem ersten freien Feld an. Ziehen verschiebt, der Griff unten rechts ändert die Größe; besetzte Felder nehmen nichts an. Pfeiltasten verschieben, Umschalt + Pfeil ändert die Größe, Entf nimmt die Zelle von der Seite.')+'</p>';
  if(st.meldung) h+='<p class="be-meldung" role="status">'+esc(st.meldung)+'</p>';
  h+='<div class="be-spalten"><div class="be-pal">'+bePaletteHtml(ctx)+'</div><div class="be-offen">'+beOffenHtml(ctx)+'</div>'+
    '<div class="be-aus">'+beAusHtml(ctx)+'</div></div>';
  return h;
}
function bePaletteHtml(ctx){
  const da=new Set(ctx.seite().bento.cells.map(c=>c.widget).filter(Boolean));
  const geht={player:!!firstAudioZone(), energy:!!firstEnergyControl(), camera:!!firstCamera(), chart:statControls().length>0,
    ansicht:beAnsichten(ctx).length>0};
  return '<div class="lbl">'+T('Widgets')+'</div><div class="be-wid">'+BE_WIDGETS.filter(([k])=>geht[k]!==false).map(([k, n])=>
    '<button type="button" class="minibtn" data-be-neu="'+k+'"'+(BE_EINZELN.includes(k) && da.has(k) ? ' disabled' : '')+'>'+T(n)+'</button>').join('')+'</div>';
}
function beOffenHtml(ctx){
  const off=beOffen(ctx.seite());
  return '<div class="lbl">'+T('Nicht platziert')+'</div>'+(off.length
    ? '<p class="hint">'+T('Gehören zur Seite, stehen aber in keiner Zelle – die Visu zeigt sie nicht. Antippen legt eine Zelle an.')+'</p>'+
      '<div class="picked">'+off.map(u=>{ const k=seCtrl(u);
        return '<span class="chip" role="button" tabindex="0" data-be-platz="'+esc(u)+'">'+esc(k ? k.name : u)+
          '<span class="rm">'+esc((k && k.roomName)||'')+'</span><span class="x" data-be-raus="'+esc(u)+'" aria-label="'+esc(T('Von der Seite nehmen'))+'">×</span></span>'; }).join('')+'</div>'
    : '<p class="hint">'+T('Alle Bausteine der Seite stehen in Zellen.')+'</p>')+
    '<select data-be-dazu aria-label="'+esc(T('Baustein zur Seite hinzufügen'))+'"><option value="">'+T('＋ hinzufügen …')+'</option>'+controlOptions()+'</select>';
}
function beAusHtml(ctx){
  const e=ctx.seite(), b=e.bento, st=beZustand(ctx), c=b.cells[st.sel], gr=beGrenzen();
  if(!c) return '<div class="lbl">'+T('Ausgewählt')+'</div><p class="hint">'+T('Keine Zelle gewählt.')+'</p>';
  const feld=(n, inhalt)=>'<div class="field"><label class="lbl">'+T(n)+'</label>'+inhalt+'</div>';
  let h='<div class="lbl">'+T('Ausgewählt')+'</div><div class="be-name">'+esc(beName(c))+'</div><div class="be-lage">'+
    [['x', 'Spalte', c.x+1, b.cols], ['y', 'Zeile', c.y+1, b.rows], ['w', 'Breite', c.w, b.cols], ['h', 'Höhe', c.h, b.rows]]
      .map(([k, n, v, hi])=>'<label>'+T(n)+'<input type="number" data-be-lage="'+k+'" min="1" max="'+hi+'" value="'+v+'"></label>').join('')+'</div>';
  const art=c.widget ? wKind(c.widget) : '', arg=c.widget ? wArg(c.widget) : '';
  if(art==='player') h+=feld('Musikzone', '<select data-be-quelle>'+audioZoneOptions(arg)+'</select>');
  else if(art==='energy') h+=feld('Baustein', '<select data-be-quelle>'+energyControlOptions(arg)+'</select>');
  else if(art==='camera') h+=feld('Baustein', '<select data-be-quelle>'+cameraOptions(arg.split('|')[0])+'</select>');
  else if(art==='ansicht') h+=feld('Ansicht', '<select data-be-quelle>'+beAnsichtOptionen(arg, ctx)+'</select>')+beAnsichtFormat(arg);
  else if(art==='chart' || art==='status'){
    const uu=arg.split(',').filter(Boolean);
    h+=feld('Bausteine', (art==='chart' ? '<select data-be-wneu>'+chartAddOptions()+'</select>'
        : '<select data-be-wneu><option value="">'+T('＋ hinzufügen …')+'</option>'+controlOptions()+'</select>')+
      '<div class="picked">'+uu.map(u=>{ const k=seCtrl(u);
        return '<span class="chip on" data-be-wweg="'+esc(u)+'">'+esc(k ? k.name : u)+'<span class="x">×</span></span>'; }).join('')+'</div>');
  }
  else if(art==='iframe'){
    h+=feld('Adresse', '<input type="url" data-be-url maxlength="'+gr.urlMax+'" placeholder="https://…" value="'+esc(c.url||'')+'">')+
      (st.urlFehler || !beUrlOk(c.url||'') ? '<p class="be-warn">'+T('Nur http- und https-Adressen mit Host, ohne Zugangsdaten.')+'</p>' : '')+
      feld('Name', '<input type="text" data-be-wname maxlength="'+gr.nameMax+'" value="'+esc(c.name||'')+'">');
  }
  else if(c.ids){
    const off=beOffen(e);
    h+=feld('Bausteine', '<div class="picked">'+c.ids.map(u=>{ const k=seCtrl(u);
        return '<span class="chip on" data-be-idweg="'+esc(u)+'">'+esc(k ? k.name : u)+'<span class="x">×</span></span>'; }).join('')+'</div>'+
      (off.length && c.ids.length<gr.bausteineMax ? '<select data-be-idneu><option value="">'+T('＋ hinzufügen …')+'</option>'+
        off.map(u=>{ const k=seCtrl(u); return '<option value="'+esc(u)+'">'+esc(k ? k.name : u)+'</option>'; }).join('')+'</select>' : ''));
  }
  return h+'<button type="button" class="minibtn be-weg" data-be-weg>'+T('Von der Seite nehmen')+'</button>';
}

// ---- Aendern ----------------------------------------------------------------------------
function beFertig(host, ctx, fokus){
  ctx.geaendert();
  beZeichnen(host);
  if(fokus!=null){ const z=host.querySelector('[data-be-z="'+fokus+'"]'); if(z) z.focus(); }
}
function beNeueZelle(host, ctx, inhalt){
  const e=ctx.seite(), b=e.bento, st=beZustand(ctx);
  if(inhalt.widget && b.cells.some(c=>c.widget===inhalt.widget && (c.url||'')===(inhalt.url||''))){
    st.meldung=T('Dieses Widget steht mit derselben Quelle schon auf der Seite.'); beZeichnen(host); return; }
  const platz=bePlatz(b, 1, 1);
  if(!platz){ st.meldung=T('Kein Feld mehr frei – Zellen verkleinern oder das Raster vergrößern.'); beZeichnen(host); return; }
  b.cells.push(Object.assign(platz, inhalt));
  st.sel=b.cells.length-1; st.meldung=''; st.urlFehler=false;
  beFertig(host, ctx, st.sel);
}
function beWidgetWert(k, ctx){
  if(k==='player') return 'player:'+(firstAudioZone()||'');
  if(k==='energy') return 'energy:'+(firstEnergyControl()||'');
  if(k==='camera') return 'camera:'+(firstCamera()||'');
  if(k==='chart') return 'chart:'+(firstChartControl()||'');
  if(k==='status'){ const c=((META && META.controls)||[])[0]; return 'status:'+(c ? c.uuid : ''); }
  if(k==='ansicht'){ // die erste Ansicht, die noch keine Zelle der Seite zeigt
    const da=new Set(ctx.seite().bento.cells.map(c=>c.widget)), ids=beAnsichten(ctx);
    return 'ansicht:'+(ids.find(id=>!da.has('ansicht:'+id)) || ids[0] || ''); }
  return k;
}
// Zelle i auf lage setzen, wenn frei -> true
function beVersetzen(ctx, i, lage){
  const b=ctx.seite().bento;
  if(!LoxRaster.bentoFrei(b.cells, b.cols, b.rows, lage, i)) return false;
  Object.assign(b.cells[i], {x:lage.x, y:lage.y, w:lage.w, h:lage.h});
  return true;
}

function beBinden(box, host){
  box.addEventListener('click', ev=>beKlick(host, ev));
  box.addEventListener('change', ev=>beAenderung(host, ev));
  box.addEventListener('keydown', ev=>beTaste(host, ev));
  box.addEventListener('pointerdown', ev=>beDown(host, ev));
}
function beKlick(host, ev){
  const ctx=host._se, e=ctx.seite(), b=e.bento, st=beZustand(ctx), t=ev.target;
  const ziel=s=>t.closest('['+s+']');
  let n;
  if((n=ziel('data-be-neu'))){ const k=n.dataset.beNeu;
    beNeueZelle(host, ctx, {widget:k==='iframe' ? 'iframe' : beWidgetWert(k, ctx)}); return; }
  if((n=ziel('data-be-raus'))){ const u=n.dataset.beRaus; e.picks=(e.picks||[]).filter(x=>x!==u); beFertig(host, ctx); return; }
  if((n=ziel('data-be-platz'))){ beNeueZelle(host, ctx, {ids:[n.dataset.bePlatz]}); return; }
  if((n=ziel('data-be-format'))){ const g=ctx.geraet(); b.format={vw:g.vw, vh:g.vh}; beFertig(host, ctx); return; }
  if((n=ziel('data-be-weg'))){ b.cells.splice(st.sel, 1); st.sel=null; beFertig(host, ctx); return; }
  if((n=ziel('data-be-wweg'))){ const c=b.cells[st.sel], art=wKind(c.widget), uu=wArg(c.widget).split(',').filter(x=>x && x!==n.dataset.beWweg);
    if(!uu.length){ st.meldung=T('Mindestens ein Baustein bleibt im Widget.'); beZeichnen(host); return; }
    c.widget=art+':'+uu.join(','); beFertig(host, ctx); return; }
  if((n=ziel('data-be-idweg'))){ const c=b.cells[st.sel], ids=c.ids.filter(x=>x!==n.dataset.beIdweg);
    if(ids.length) c.ids=ids; else { b.cells.splice(st.sel, 1); st.sel=null; }
    beFertig(host, ctx); return; }
}
function beAenderung(host, ev){
  const ctx=host._se, e=ctx.seite(), b=e.bento, gr=beGrenzen(), st=beZustand(ctx), t=ev.target, c=b.cells[st.sel];
  const zahl=(v, lo, hi)=>Math.max(lo, Math.min(hi, parseInt(v, 10)||lo));
  if(t.dataset.beRaster){
    const k=t.dataset.beRaster, neu=zahl(t.value, k==='cols' ? gr.spaltenMin : gr.zeilenMin, k==='cols' ? gr.spaltenMax : gr.zeilenMax);
    const cols=k==='cols' ? neu : b.cols, rows=k==='rows' ? neu : b.rows;
    if(b.cells.some(z=>z.x+z.w>cols || z.y+z.h>rows)){
      st.meldung=T('Zellen lägen außerhalb des Rasters – erst verschieben oder verkleinern.'); beZeichnen(host); return; }
    b[k]=neu; st.meldung=''; beFertig(host, ctx); return;
  }
  if(t.dataset.beLage && c){
    const lage={x:c.x, y:c.y, w:c.w, h:c.h}, k=t.dataset.beLage, v=parseInt(t.value, 10);
    if(k==='x' || k==='y') lage[k]=v-1; else lage[k]=v;
    if(!beVersetzen(ctx, st.sel, lage)){ st.meldung=T('Dort ist kein Platz frei.'); beZeichnen(host); return; }
    st.meldung=''; beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-quelle') && c){
    const art=wKind(c.widget), werte=art==='camera' ? (wArg(c.widget).split('|')[1]||'') : '';
    c.widget=art+':'+t.value+(werte ? '|'+werte : ''); beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-wneu') && c && t.value){
    const art=wKind(c.widget), uu=wArg(c.widget).split(',').filter(Boolean);
    if(uu.indexOf(t.value)<0 && uu.length<svMax()) uu.push(t.value);
    c.widget=art+':'+uu.join(','); beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-idneu') && c && t.value){
    if(c.ids.indexOf(t.value)<0 && c.ids.length<gr.bausteineMax) c.ids.push(t.value);
    beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-dazu') && t.value){
    e.picks=e.picks||[]; if(e.picks.indexOf(t.value)<0) e.picks.push(t.value);
    beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-url') && c){
    const u=t.value.trim();
    if(beUrlOk(u)){ c.url=u; st.urlFehler=false; } else st.urlFehler=true;
    beFertig(host, ctx); return;
  }
  if(t.hasAttribute('data-be-wname') && c){
    const nm=t.value.trim().slice(0, gr.nameMax); if(nm) c.name=nm; else delete c.name;
    beFertig(host, ctx); return;
  }
}
function beTaste(host, ev){
  const z=ev.target.closest('[data-be-z]'); if(!z) return;
  const ctx=host._se, b=ctx.seite().bento, st=beZustand(ctx), i=+z.dataset.beZ, c=b.cells[i]; if(!c) return;
  const pfeil={ArrowLeft:[-1, 0], ArrowRight:[1, 0], ArrowUp:[0, -1], ArrowDown:[0, 1]}[ev.key];
  if(ev.key==='Enter' || ev.key===' '){ ev.preventDefault(); st.sel=i; beZeichnen(host); const n=host.querySelector('[data-be-z="'+i+'"]'); if(n) n.focus(); return; }
  if(ev.key==='Delete' || ev.key==='Backspace'){ ev.preventDefault(); b.cells.splice(i, 1); st.sel=null; beFertig(host, ctx); return; }
  if(!pfeil) return;
  ev.preventDefault();
  const lage=ev.shiftKey ? {x:c.x, y:c.y, w:c.w+pfeil[0], h:c.h+pfeil[1]} : {x:c.x+pfeil[0], y:c.y+pfeil[1], w:c.w, h:c.h};
  st.sel=i;
  if(beVersetzen(ctx, i, lage)){ st.meldung=''; beFertig(host, ctx, i); }
  else { beZeichnen(host); const n=host.querySelector('[data-be-z="'+i+'"]'); if(n) n.focus(); }
}

// ---- Ziehen ----------------------------------------------------------------------------
function beDown(host, ev){
  const griff=ev.target.closest('[data-be-griff]'), z=ev.target.closest('[data-be-z]');
  if(!z || ev.button>0) return;
  const ctx=host._se, i=+z.dataset.beZ, c=ctx.seite().bento.cells[i], fl=host.querySelector('[data-be-flaeche]');
  if(!c || !fl) return;
  ev.preventDefault();
  beZustand(ctx).sel=i;
  const f=beFlaeche(ctx), r=fl.getBoundingClientRect();
  const punkt=e=>({x:(e.clientX-r.left)/r.width*f.g.vw, y:(e.clientY-r.top)/r.height*f.g.vh});
  BE_ZIEHEN={host, ctx, i, f, punkt, griff:!!griff, start:beFeld(f, punkt(ev).x, punkt(ev).y),
             c0:{x:c.x, y:c.y, w:c.w, h:c.h}, lage:null, el:z};
  try{ z.setPointerCapture(ev.pointerId); }catch(e){}
  window.addEventListener('pointermove', beMove);
  window.addEventListener('pointerup', beUp);
  window.addEventListener('pointercancel', beUp);
}
function beMove(ev){
  const d=BE_ZIEHEN; if(!d) return;
  const p=d.punkt(ev), fd=beFeld(d.f, p.x, p.y), c0=d.c0;
  const lage=d.griff ? {x:c0.x, y:c0.y, w:Math.max(1, fd.x-c0.x+1), h:Math.max(1, fd.y-c0.y+1)}
                     : {x:c0.x+fd.x-d.start.x, y:c0.y+fd.y-d.start.y, w:c0.w, h:c0.h};
  const b=d.ctx.seite().bento, frei=LoxRaster.bentoFrei(b.cells, b.cols, b.rows, lage, d.i);
  d.lage=frei ? lage : null;
  d.el.setAttribute('style', beKasten(d.f, frei ? lage : c0));
  d.el.classList.toggle('nein', !frei);
}
function beUp(){
  const d=BE_ZIEHEN; BE_ZIEHEN=null;
  window.removeEventListener('pointermove', beMove);
  window.removeEventListener('pointerup', beUp);
  window.removeEventListener('pointercancel', beUp);
  if(!d) return;
  const c0=d.c0, l=d.lage;
  if(l && (l.x!==c0.x || l.y!==c0.y || l.w!==c0.w || l.h!==c0.h) && beVersetzen(d.ctx, d.i, l)){
    beZustand(d.ctx).meldung=''; beFertig(d.host, d.ctx, d.i); }
  else { beZeichnen(d.host); const n=d.host.querySelector('[data-be-z="'+d.i+'"]'); if(n) n.focus(); }
}
