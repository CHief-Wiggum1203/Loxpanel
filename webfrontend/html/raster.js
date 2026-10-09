/* LoxPanel - gemeinsame Rasterrechnung fuer die Visu (panel.html) und den
   Konfigurator (config.html), ausgeliefert unter /raster.js. Reine Rechnung
   ohne DOM: die Visu misst ihre Flaeche und ihre Masse und uebergibt sie, der
   Konfigurator rechnet ein Geraet aus seiner gemeldeten Groesse mit den
   Standardmassen vor (Assistent Schritt 1, Punkt 9). So zeigt der Assistent
   dasselbe Raster, das die Visu am Geraet baut. */
(function(g){
'use strict';

// Kachelfaktor (Punkt 1): Bezugskachel 170 x 150 px, Faktor 0,85 bis 2;
// Kopfzeile und Werteleiste wachsen mit (KOPF_H, LEISTE_H bei Faktor 1).
const KACHEL_REF=170, KACHEL_REF_H=150, KS_MIN=0.85, KS_MAX=2, KOPF_H=64, LEISTE_H=48;

// Masse der Visu im automatischen Raster, in CSS-Pixeln (dort wirkt keine
// Skalierung): Abstand und Innenrand des Rasters und die Hoehe der
// Seitenpunkte wie im CSS von panel.html (.grid --gap, --pad, --punkte-h),
// die Tab-Leiste aus .tab (2 x 13 px Innenabstand, 28 px Symbol, 1 px Linie
// oben). Die Visu misst selbst; der Konfigurator rechnet ein Geraet damit vor.
// Ein Browser-Test vergleicht die Werte mit der gemessenen Visu.
const VISU_MASSE={gap:10, pad:10, punkteH:14, tabsH:55};

// Breite UND Hoehe zaehlen: eine flache Kachel (2x3 auf dem 4"-Panel: 225 x 128)
// traegt sonst die Schrift ihrer Breite und laeuft unten ueber.
function kachelFaktorFuer(breite, hoehe){
  const k=Math.min(breite/KACHEL_REF, (hoehe>0) ? hoehe/KACHEL_REF_H : Infinity);
  return Math.min(KS_MAX, Math.max(KS_MIN, k));
}

// Quadratischer Schirm (4"-Panel): Breite und Hoehe weniger als ein Zehntel auseinander.
function quadratisch(w, h){ return Math.abs(w-h) < 0.1*Math.max(w, h); }

// Groesse einer Kachel im Raster: eine Zahl (Breite 1 | 2) oder {w, h} aus dem
// Seiten-Editor (Punkt 10: 1x1, 2x1, 2x2). Breit nur, wo zwei Spalten da sind,
// hoch nur, wo sie auch breit ist und zwei Zeilen da sind.
function groesse(b, cols, rows){
  const w=Math.min(((typeof b==='number') ? b : (b && b.w))===2 ? 2 : 1, Math.max(1, cols));
  const h=(w===2 && rows>=2 && typeof b==='object' && b && b.h===2) ? 2 : 1;
  return {w:w, h:h};
}
// Lage der Kacheln im Raster, wie CSS sie setzt (grid-auto-flow: row dense):
// je Kachel Zeile und Spalte. Breite Kacheln (w = 2) belegen zwei Spalten, eine
// Luecke davor fuellt die naechste schmale Kachel. Eine hohe (h = 2) belegt zwei
// Zeilen derselben Seite: in der letzten Zeile einer Seite rueckt sie auf die
// naechste (hoch: die Visu setzt dann jede Kachel an ihre Stelle, weil der
// Fluss des Browsers die Seitengrenze nicht kennt). Daraus die Seitenzahl und
// die Rastpunkte (jede Kachel in der ersten Zeile einer Seite).
function rasterLage(groessen, cols, rows){
  const belegt=[], zeile=[], spalte=[], R=Math.max(1,rows);
  const frei=(r,c,w,h)=>{ for(let y=0;y<h;y++) for(let k=0;k<w;k++) if(belegt[r+y] && belegt[r+y][c+k]) return false; return true; };
  let hoch=false;
  for(const b of groessen){
    const {w, h}=groesse(b, cols, rows);
    if(h>1) hoch=true;
    let r=0, c=-1;
    while(c<0){
      if(r%R<=R-h){ for(let cc=0; cc+w<=cols; cc++){ if(frei(r,cc,w,h)){ c=cc; break; } } }
      if(c<0) r++;
    }
    for(let y=0;y<h;y++){ belegt[r+y]=belegt[r+y]||[]; for(let k=0;k<w;k++) belegt[r+y][c+k]=true; }
    zeile.push(r); spalte.push(c);
  }
  const snaps=new Set(), gesehen=new Set();
  zeile.forEach((z,i)=>{ if(z%R===0 && !gesehen.has(z)){ gesehen.add(z); snaps.add(i); } });
  return {zeile:zeile, spalte:spalte, hoch:hoch, seiten:Math.max(1, Math.ceil(belegt.length/R)), snaps:snaps};
}

// Festes Raster aus dem Profil (cols x rows): mit Split verdoppelt es sich quer
// auf doppelt so viele Spalten und hochkant, wenn der Schirm schmal genug ist,
// auf doppelt so viele Zeilen; ohne Split oder auf einer Widget-Seite nie.
function festesRaster(e){
  const {cols, rows, w, h}=e;
  if(!e.split || e.widget) return [cols, rows];
  if(w>h) return [cols*2, rows];
  if(h>w && w/h < (cols/rows)/Math.SQRT2) return [cols, rows*2];
  return [cols, rows];
}

// Automatisches Raster (Profil "Automatisch"): Spalten und Zeilen aus der
// freien Flaeche und der Zielgroesse einer Kachel. Ein groesserer Schirm zeigt
// mehr Kacheln statt groesserer, die Zeilen machen die Kacheln etwa
// quadratisch. Ein Widget belegt ganze Kachelspalten (quer) bzw. -zeilen
// (hochkant): paneCols davon, sonst rund den Anteil paneShare.
// Kennt die Rechnung die Kacheln der Seite (breiten: 1 oder 2 je Kachel),
// wachsen sie, wenn alle auf eine Seite passen, bis die Seite voll ist,
// hoechstens auf wachsen * ziel; bliebe bei mehreren Seiten die letzte mehr
// als ein Drittel leer, werden sie kleiner, sobald das eine Seite spart,
// hoechstens bis ziel / wachsen (Punkt 16). Beides nur ohne Widget oder neben
// einem mit fester Breite: mit weniger Spalten liesse sich ein Anteil nicht
// halten (2 von 5 Spalten sind 40 %, 2 von 4 schon 50 %).
// e: {w, h, ziel, wachsen, gap, pad, tabsH, punkteH, widget, paneCols,
//     paneShare, breiten, seitenQuer, kopfH(ks), leisteH(ks)}
// -> {cols, rows, k, p, ks, gesamt, kb, pPx?}: k und p sind die Anteile von
// Kacheln und Widget an der Aufteilung, pPx die Hoehe des Widgets hochkant.
function autoRaster(e){
  const w=e.w, hoehe=e.h, ziel=e.ziel, wachsen=e.wachsen||1;
  const gap=e.gap||0, pad=e.pad||0, tabsH=e.tabsH||0, punkteH=e.punkteH||0;
  const widget=!!e.widget, paneCols=e.paneCols||0, paneShare=e.paneShare||0;
  const breiten=e.breiten||[], kopfH=e.kopfH||(()=>0), leisteH=e.leisteH||(()=>0);
  const hoch=hoehe>w;
  const anzahl=(laenge,kachel)=>Math.max(1, Math.round((laenge-2*pad+gap)/(kachel+gap)));
  const abgeben=n=>Math.min(n-1, Math.max(1, paneCols>0 ? paneCols : Math.round(n*paneShare)));
  // Raster fuer eine Spaltenzahl (vor dem Abgeben an das Widget): Kachelbreite
  // -> Kachelfaktor -> Hoehe der Kopfzeile -> Zeilen. Mit der Zeilenzahl steht
  // die Hoehe fest; ist die Kachel flach, begrenzt sie den Faktor (die
  // Kopfzeile wird dann hoechstens ein paar Pixel niedriger).
  const fuer=(gesamt, punkte)=>{
    const kb=(w-2*pad-(gesamt-1)*gap)/gesamt, ksw=kachelFaktorFuer(kb);
    const h=hoehe-tabsH-kopfH(ksw)-leisteH(ksw)-(punkte?punkteH:0);
    const rows=anzahl(h, kb), zh=(h-2*pad-(rows-1)*gap)/rows;   // zh: Hoehe einer Kachelzeile
    const ks=kachelFaktorFuer(kb, zh);
    let r;
    if(!widget) r={cols:gesamt, rows:rows, k:1, p:0, ks:ks};
    else if(hoch){   // hochkant: Widget unter den Kacheln, seine Hoehe in px (p Zeilen samt Abstand)
      if(rows<2) r={cols:gesamt, rows:1, k:1, p:1, ks:ks};
      else { const p=abgeben(rows); r={cols:gesamt, rows:rows-p, k:rows-p, p:p, ks:ks, pPx:p*(zh+gap)}; } }
    else if(gesamt<2) r={cols:1, rows:rows, k:1, p:1, ks:ks};
    else { const p=abgeben(gesamt); r={cols:gesamt-p, rows:rows, k:gesamt-p, p:p, ks:ks}; }
    r.gesamt=gesamt; r.kb=kb;
    return r;
  };
  const passt=(c,rw)=>breiten.length>0 && rasterLage(breiten,c,rw).seiten<=1;
  const seitenVon=r=>rasterLage(breiten, r.cols, r.rows).seiten;
  // Mehrere Seiten und die letzte mehr als ein Drittel leer (in Zellen, eine
  // breite Kachel belegt zwei, eine hohe vier)? Eine einzelne Seite fuellt das Wachsen.
  const letzteZuLeer=r=>{
    const l=rasterLage(breiten, r.cols, r.rows), zellen=r.cols*r.rows;
    if(l.seiten<2) return false;
    let belegt=0;
    l.zeile.forEach((z,i)=>{ if(Math.floor(z/r.rows)===l.seiten-1){ const g=groesse(breiten[i], r.cols, r.rows); belegt+=g.w*g.h; } });
    return 3*(zellen-belegt)>zellen;
  };
  const rechne=punkte=>{
    let r=fuer(anzahl(w, ziel), punkte);
    if((!widget || paneCols>0) && passt(r.cols,r.rows)){
      for(let c=r.gesamt-1; c>=1; c--){
        const n=fuer(c, punkte);
        if(n.kb>wachsen*ziel || !passt(n.cols,n.rows)) break;
        r=n;
      }
    }
    else if((!widget || paneCols>0) && breiten.length>0 && letzteZuLeer(r)){
      // Schrumpfen: je eine Spalte mehr, bis die letzte Seite voll genug ist
      // oder die Kachel unter ziel / wachsen fiele; genommen wird nur, was eine Seite spart.
      for(let c=r.gesamt+1; letzteZuLeer(r); c++){
        const n=fuer(c, punkte);
        if(n.kb<ziel/wachsen) break;
        if(seitenVon(n)<seitenVon(r)) r=n;
      }
    }
    return r;
  };
  let r=rechne(false);
  // Waagerechte Seiten mit Punkten darunter: die Punkte nehmen Hoehe, also
  // noch einmal rechnen, sobald es mehr als eine Seite gibt (weniger Hoehe
  // gibt nie weniger Seiten, das Ergebnis steht nach dem zweiten Lauf).
  if(e.seitenQuer && breiten.length>0 && rasterLage(breiten, r.cols, r.rows).seiten>1) r=rechne(true);
  return r;
}

g.LoxRaster={KACHEL_REF, KACHEL_REF_H, KS_MIN, KS_MAX, KOPF_H, LEISTE_H, VISU_MASSE,
  kachelFaktorFuer, quadratisch, groesse, rasterLage, festesRaster, autoRaster};
})(typeof window!=='undefined' ? window : globalThis);
