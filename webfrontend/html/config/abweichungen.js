// LoxPanel-Konfigurator, LoxOS (Fork, docs/VISION.md "Uebersicht „Was ist eingestellt?“"):
// Karte oben im Reiter Allgemein einer Ansicht bzw. oben in Vorgaben -> Darstellung (die
// Vorgaben haben keinen Reiter Allgemein). Sie listet jeden ui-Schluessel, den die Ansicht
// selbst setzt (in den Vorgaben jeden gesetzten), mit Wert, was ohne ihn gaelte, Sprung zum
// Reiter und "× zurücksetzen"; "Alles auf Standard" fragt in der Seite nach. Zurueckgesetzt
// wird nur in der Arbeitskopie (PANELS), wirksam mit "Speichern". Eingehaengt ueber einen
// Aufruf in erbtZeichnen() (ansicht-editor.js), das renderEditor() und markDirty() rufen.

// Schluessel -> Name (wie am Feld im Editor, uebersetzt ueber i18n.js) und Reiter der
// Ansicht (PCONF_TABS). Eine Zeile je Eintrag: tests/test_abweichungen.py liest die Tabelle
// und prueft, dass jeder ui-Schluessel aus _panel_export() und THEME_UI_KEYS darin steht.
const ABWEICHUNG_FELDER={
  lang:{name:'Sprache', reiter:'allgemein'},
  panes:{name:'Widget je Standard-Seite', reiter:'inhalt'},
  valueBar:{name:'Werteleiste', reiter:'inhalt'},
  catFilter:{name:'Tipp auf eine Sprungmarke', reiter:'inhalt'},
  player:{name:'Audio-Zone des Widgets', reiter:'inhalt'},
  grid:{name:'Kachel-Layout', reiter:'raster'},
  cols:{name:'Kachel-Layout: Spalten', reiter:'raster'},
  rows:{name:'Kachel-Layout: Zeilen', reiter:'raster'},
  fill:{name:'Bildschirm füllen', reiter:'raster'},
  split:{name:'Split-Screen', reiter:'raster'},
  paneCols:{name:'Widget-Breite', reiter:'raster'},
  nudgeX:{name:'Horiz. Versatz (px)', reiter:'raster'},
  scale:{name:'Skalierung', reiter:'raster'},
  tileSize:{name:'Zielkachel', reiter:'raster'},
  tileSet:{name:'Kachel-Set', reiter:'aussehen'},
  tileHue:{name:'Farbton (Touch)', reiter:'aussehen'},
  tileHueEdge:{name:'Farbton (Edge)', reiter:'aussehen'},
  tileActive:{name:'Aktive Kachel', reiter:'aussehen'},
  baseColor:{name:'Grundfarbe', reiter:'aussehen'},
  tileLayout:{name:'Kachel-Aufbau', reiter:'aussehen'},
  font:{name:'Schriftart', reiter:'aussehen'},
  textColor:{name:'Schriftfarbe (Haupttext)', reiter:'aussehen'},
  bold:{name:'Schriftstärke', reiter:'aussehen'},
  iconSize:{name:'Icon-Größe', reiter:'aussehen'},
  nameSize:{name:'Haupttext-Größe', reiter:'aussehen'},
  subSize:{name:'Zweittext-Größe', reiter:'aussehen'},
  roomSize:{name:'Raum-Größe', reiter:'aussehen'},
  bigSize:{name:'Messwert-Größe', reiter:'aussehen'},
  hausAufbau:{name:'Hausübersicht: Aufbau', reiter:'aussehen'},
  hausAktivOhne:{name:'Hausübersicht: zählt nicht unter „Gerade aktiv“', reiter:'aussehen'},
  hausEnergie:{name:'Hausübersicht: Energie im Kopf', reiter:'aussehen'},
  overlay:{name:'Aktiv-Overlay', reiter:'aussehen'},
  svPane:{name:'Screensaver: zweite Fläche', reiter:'verhalten'},
  reloadHours:{name:'Auto-Neustart alle (Std.)', reiter:'verhalten'},
  dpmsOff:{name:'Display aus nach', reiter:'verhalten'},
  nightDim:{name:'Nachts abdunkeln', reiter:'verhalten'},
  nightWake:{name:'Aufhellen bei Berührung', reiter:'verhalten'},
  nightClock:{name:'Nacht-Uhr', reiter:'verhalten'},
  nightClockBright:{name:'Helligkeit der Nacht-Uhr', reiter:'verhalten'},
  pinMerken:{name:'PIN merken (Sek.)', reiter:'verhalten'},
  gesten:{name:'Zwei-Finger-Gesten', reiter:'verhalten'},
  gestenRaum:{name:'Raum außerhalb von Raumseiten', reiter:'verhalten'},
  gestenHinweis:{name:'Hinweis-Symbol', reiter:'verhalten'},
  hausAus:{name:'Haus aus (Dreifachtipp)', reiter:'verhalten'},
  raumVerlassen:{name:'Raum verlassen (Doppeltipp)', reiter:'verhalten'},
};
// Was "Alles auf Standard" nicht anfasst: Inhalt und Look (Widgets, Werteleiste, die
// Audio-Zone des Widgets, Kachel-Set und Farbton). Sie stehen in der Liste mit eigenem Knopf.
const ABWEICHUNG_BLEIBT=['panes','svPane','valueBar','player','tileSet','tileHue','tileHueEdge','tileActive'];
// Reiter der Ansicht -> Reiter der Vorgaben (VG_TABS), in dem derselbe Schluessel steht
const ABWEICHUNG_REITER_VORGABEN={allgemein:'appearance', inhalt:'appearance', seiten:'appearance',
  raster:'appearance', aussehen:'appearance', verhalten:'verhalten'};

// Gesetzt heisst: ein Wert, kein leeres Objekt und keine leere Liste
function abwGesetzt(v){
  if(!gesetzt(v)) return false;
  if(Array.isArray(v)) return v.length>0;
  return typeof v!=='object' || Object.keys(v).length>0;
}
// Die Zeilen: bekannte Schluessel in der Reihenfolge der Tabelle, unbekannte dahinter
function abwSchluessel(ui){
  const da=Object.keys(ui||{}).filter(k=>abwGesetzt(ui[k]));
  return Object.keys(ABWEICHUNG_FELDER).filter(k=>da.indexOf(k)>=0).concat(da.filter(k=>!ABWEICHUNG_FELDER[k]));
}
// Ohne Eintrag erscheint ein Schluessel mit seinem technischen Namen, nie gar nicht
function abwName(k){ const f=ABWEICHUNG_FELDER[k]; return f ? T(f.name) : k; }
function abwReiter(k, istVorgabe){
  const f=ABWEICHUNG_FELDER[k]; if(!f) return '';
  return istVorgabe ? ABWEICHUNG_REITER_VORGABEN[f.reiter] : f.reiter;
}
// Name einer UUID (Raum, Baustein, Taster, Energie), sonst die UUID
function abwUuidName(v){
  const m=META||{}, alle=[].concat(m.rooms||[], m.controls||[], m.gestenTaster||[], m.hausEnergien||[]);
  const o=alle.find(x=>x && x.uuid===v); return o ? o.name : String(v);
}
// Wert als Text: wertText() fuer alles, was es kennt; Listen, Objekte, An/Aus, Kachel-Set,
// Farbton und aktive Kachel hier, damit nie "[object Object]" oder "true" dasteht
function abwWert(k, v){
  if(Array.isArray(v)) return v.map(String).join(', ');
  if(typeof v==='object') return T('eigene Einstellung');
  if(k==='grid' && v==='auto') return T('Automatisch (Tablet)');
  if(k==='tileSet'){ const s=kachelSetMeta(v); return s ? T(s.label) : String(v); }
  const sets=(META&&META.kachelSets)||[];
  const ton=sets.find(s=>s.farbton && s.farbton.schluessel===k);
  if(ton){ const a=ton.farbton.auswahl.find(x=>x.wert===Number(v)); return (a ? T(a.label)+' ' : '')+fmtZahl(v)+'°'; }
  if(k==='tileActive'){ const s=sets.find(x=>x.aktiv), a=s && s.aktiv.auswahl.find(x=>x.key===v); return a ? T(a.label) : String(v); }
  if(k==='player'||k==='gestenRaum'||k==='hausEnergie'||k==='hausAus') return abwUuidName(v);
  const t=wertText(k, v);
  if(typeof v==='boolean' && t===String(v)) return v ? T('An') : T('Aus');
  return t;
}
// Was ohne den Eintrag gaelte: in einer Ansicht Vorgabe oder Standard, in den Vorgaben der Standard
function abwOhne(k, ui, istVorgabe){
  return giltText(k, istVorgabe ? {v:standardWert(k,{}), quelle:T('Standard')} : wasGiltOhneEigenen(k, ui));
}
// "gilt für n von m Ansichten": Ansichten ohne eigenen Wert fuer k
function abwGiltFuer(k){
  const ids=ansichtIds(), eigene=ids.filter(id=>abwGesetzt(((PANELS[id]||{}).ui||{})[k]));
  return T('gilt für {n} von {m} Ansichten').replace('{n}',ids.length-eigene.length).replace('{m}',ids.length);
}

function abweichungenHtml(ui, istVorgabe){
  ui=ui||{};
  const keys=abwSchluessel(ui), weg=keys.filter(k=>ABWEICHUNG_BLEIBT.indexOf(k)<0);
  const tabs=istVorgabe ? VG_TABS : PCONF_TABS, eigen=istVorgabe ? '' : 'allgemein';
  const zeilen=keys.map(k=>{
    const ohne=abwOhne(k, ui, istVorgabe), r=abwReiter(k, istVorgabe), tab=tabs.find(t=>t.k===r);
    return '<div class="abw-zeile" data-abw="'+esc(k)+'"><div class="abw-text">'+
        '<b class="abw-name">'+esc(abwName(k))+'</b>'+
        '<span class="abw-wert">'+esc(abwWert(k, ui[k]))+'</span>'+
        '<span class="abw-ohne">'+esc(T('sonst gilt: {w}').replace('{w}', ohne))+'</span></div>'+
      '<div class="abw-knoepfe">'+
        (tab && r!==eigen ? '<button type="button" class="minibtn" data-abw-reiter="'+esc(r)+'">'+esc(T(tab.label))+' →</button>' : '')+
        zurueckKnopf('data-abw-zurueck', k, ohne)+'</div></div>';
  }).join('');
  const leer=istVorgabe ? T('Alles auf Standard – die Vorgaben stellen nichts ein.')
                        : T('Alles auf Standard – diese Ansicht stellt nichts selbst ein, es gelten Vorgaben und Standard.');
  return '<div class="card abw" id="abwKarte"'+(istVorgabe ? ' data-abw-vorgabe' : '')+'><h3>'+esc(T('Was ist eingestellt?'))+'</h3>'+
    '<p class="note">'+esc(istVorgabe
      ? T('Alles, was die Vorgaben einstellen. Zurücksetzen entfernt den Wert, dann gilt der Standard in jeder Ansicht ohne eigenen Wert. Wirksam mit „Speichern“.')
      : T('Alles, was diese Ansicht selbst einstellt. Zurücksetzen entfernt den eigenen Wert, dann gilt die Vorgabe oder der Standard. Wirksam mit „Speichern“.'))+'</p>'+
    (keys.length ? '<div class="abw-liste">'+zeilen+'</div>' : '<p class="abw-leer">'+esc(leer)+'</p>')+
    (weg.length ? '<div class="actions"><button type="button" class="btn ghost" data-abw-alle>'+esc(T('Alles auf Standard'))+'</button></div>'+
      '<div class="abw-frage" hidden></div>' : '')+
  '</div>';
}

// Bindet die Karte in host: ui ist das ui-Objekt der Arbeitskopie, fertig() laeuft nach
// jedem Zuruecksetzen (markieren und den Editor neu zeichnen)
function abweichungenBinden(host, ui, fertig){
  const karte=host && host.querySelector('#abwKarte'); if(!karte) return;
  const istVorgabe=karte.hasAttribute('data-abw-vorgabe');
  karte.querySelectorAll('[data-abw-zurueck]').forEach(b=>b.onclick=()=>{ delete ui[b.dataset.abwZurueck]; fertig(); });
  karte.querySelectorAll('[data-abw-reiter]').forEach(b=>b.onclick=()=>{
    subMerken(rubric, b.dataset.abwReiter); renderSubtabs(); showSub(b.dataset.abwReiter); });
  const alle=karte.querySelector('[data-abw-alle]'), frage=karte.querySelector('.abw-frage');
  if(!alle || !frage) return;
  alle.onclick=()=>{
    const keys=abwSchluessel(ui), weg=keys.filter(k=>ABWEICHUNG_BLEIBT.indexOf(k)<0), bleibt=keys.filter(k=>ABWEICHUNG_BLEIBT.indexOf(k)>=0);
    frage.innerHTML='<p><b>'+esc(T('Das wird zurückgesetzt:'))+'</b></p>'+
      '<ul data-abw-weg>'+weg.map(k=>'<li>'+esc(abwName(k)+(istVorgabe ? ' · '+abwGiltFuer(k) : ''))+'</li>').join('')+'</ul>'+
      (bleibt.length ? '<p class="note" data-abw-bleibt>'+esc(T('Bleibt, mit eigenem Knopf: {liste}').replace('{liste}', bleibt.map(abwName).join(', ')))+'</p>' : '')+
      '<p class="note">'+esc(T('Wirksam erst mit „Speichern“.'))+'</p>'+
      '<div class="actions"><button type="button" class="btn" data-abw-ja>'+esc(T('Zurücksetzen'))+'</button>'+
        '<button type="button" class="btn ghost" data-abw-nein>'+esc(T('Abbrechen'))+'</button></div>';
    frage.hidden=false; alle.hidden=true;
    frage.querySelector('[data-abw-nein]').onclick=()=>{ frage.hidden=true; frage.innerHTML=''; alle.hidden=false; };
    frage.querySelector('[data-abw-ja]').onclick=()=>{ weg.forEach(k=>{ delete ui[k]; }); fertig(); };
  };
}

// Karte in den ersten Reiter des Editors setzen (Ansicht: Allgemein, Vorgaben: Darstellung)
// und binden; ersetzt eine vorhandene, damit sie Aenderungen aus anderen Reitern zeigt
function abweichungenEinhaengen(){
  const p=PANELS[cur], host=$('#pconfHost'); if(!p || !host) return;
  const istVorgabe=!!p.__global, sec=host.querySelector('.spane[data-sub="'+(istVorgabe ? VG_TABS[0].k : 'allgemein')+'"]');
  if(!sec) return;
  const alt=sec.querySelector('#abwKarte'), neu=document.createElement('div');
  neu.innerHTML=abweichungenHtml(p.ui, istVorgabe);
  if(alt) alt.replaceWith(neu.firstChild); else sec.prepend(neu.firstChild);
  abweichungenBinden(host, p.ui||{}, ()=>{ markDirty(); renderEditor(); });
}
