/* LoxOS (Fork, docs/VISION.md): Raum-Display-Zellen einer Bento-Seite.

   Eine Zelle "ansicht:<Kennung>" (bento.py, bentoAnsicht() in bento.js) zeigt
   eine ganze Ansicht als eigene Visu in einem iframe derselben Herkunft
   (?panel=<Kennung>&eingebettet=1). Diese Datei haelt beide Seiten:

   Die Visu IN der Zelle (EINGEBETTET, verbindung.js) ist kein Geraet: Sie
   meldet sich ohne Namen und ohne Kopplungscode (der localStorage ist der der
   Visu um die Zelle), zeigt keine Uhr-Seite (start.js), kehrt nach der
   Leerlaufzeit nur auf ihre Startseite zurueck (ruheNachLeerlauf() in
   ruhe.js) und fasst die Bruecken der Kiosk-Apps (KIOSK_APPS, display.js)
   nicht an - ein iframe sieht sie in der App mit, und die Zelle schaltete
   sonst Schoner und Display des ganzen Geraets. Klingel, Wecker, Nacht und
   Display-Befehle schickt ihr der Server gar nicht erst (_eingebettet in
   bento.py).

   Die Visu UM die Zelle merkt von Beruehrungen im iframe nichts (die Events
   bleiben in dessen Dokument); ohne Meldung kaeme ihre Uhr-Seite mitten in
   der Bedienung. Die Zelle meldet darum jede Bedienung (hoechstens alle
   EINGEBETTET_MELDEN_MS) per postMessage, die Visu um sie behandelt das wie
   eine eigene Beruehrung. */

const EINGEBETTET_MELDEN_MS=1000;
const EINGEBETTET_AKTIV='loxpanelAktiv';   // Art der Nachricht an die Visu um die Zelle

if(EINGEBETTET){
  for(const k in KIOSK_APPS){
    try{ Object.defineProperty(window, KIOSK_APPS[k], {value:undefined, writable:true, configurable:true}); }
    catch(e){ /* nicht ueberschreibbar: bleibt, wie die App sie eingehaengt hat */ }
  }
  let zuletzt=0;
  const melden=()=>{ const t=Date.now(); if(t-zuletzt<EINGEBETTET_MELDEN_MS) return; zuletzt=t;
    try{ parent.postMessage({t:EINGEBETTET_AKTIV}, location.origin); }catch(e){} };
  ['pointerdown','keydown','input','wheel'].forEach(ev=>window.addEventListener(ev, melden, {capture:true, passive:true}));
}

// Leerlauf in der Zelle (nachRuhe -> ruheNachLeerlauf): wie das Display, fuer
// das die Ansicht gebaut ist - gemerkte PIN und Hilfe weg, zurueck auf die
// erste Seite -, nur ohne Uhr-Seite.
function eingebettetNachLeerlauf(){
  pinVergessen(); gestenHilfeWeg();
  katFilter=null; goTab(tabsCfg[0]||'favoriten');
}

// Visu um die Zelle: eine Bedienung in einer ihrer Raum-Display-Zellen weckt
// wie eine Beruehrung (startseite.js). Nur Nachrichten derselben Herkunft aus
// einem iframe dieser Seite zaehlen.
function eingebettetQuelle(quelle){
  return [...document.querySelectorAll('#grid.bento > .bz[data-widget="ansicht"] iframe')]
    .some(f=>f.contentWindow===quelle);
}
window.addEventListener('message', e=>{
  if(e.origin!==location.origin || !e.data || e.data.t!==EINGEBETTET_AKTIV || !eingebettetQuelle(e.source)) return;
  nightWake();
  if(!saverOn()) resetIdle();
});
