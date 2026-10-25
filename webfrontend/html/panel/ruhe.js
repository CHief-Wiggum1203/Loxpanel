/* LoxOS (Fork, docs/VISION.md): Ruhemodus der Visu.

   Mit devices[name].ruhe (theme.ruhe, live {t:"ruhe"}) steuert der
   Praesenzmelder des Geraets die Uhr-Seite statt der Leerlaufzeit: Meldet er
   niemanden, steht die Nacht-Uhr, zu jeder Tageszeit; meldet er jemanden,
   steht die zuletzt gezeigte Seite und der Ruhe-Timer zeigt keine Uhr. Das
   Display wird dabei nie ausgeschaltet (armDpms, appLeerlauf und die
   display-Nachricht in verbindung.js fragen RUHE).

   Nichts wird hier nachgebaut: Die Ruhe-Uhr ist die Nacht-Uhr
   (nachtUhrSetzen(), .saver.nacht, Helligkeit NIGHT.uhrHell), nachtUhrAn()
   fragt dazu ruheAn(). Ein Tipp weckt wie immer (startseite.js); meldet der
   Melder weiter niemanden, kehrt die Uhr nach SAVER_IDLE_MS zurueck
   (ruheNachLeerlauf() in nachRuhe()). */

let RUHE=false;
// Ruhe-Uhr jetzt? Nur mit Ruhemodus und solange der Melder niemanden meldet;
// nie in der Vorschau eines Entwurfs (ENTWURF, verbindung.js): die zeigt Seiten
function ruheAn(){ return RUHE && !DISP.presence && !ENTWURF; }
// Stand des Melders auf die Uhr-Seite legen: niemand da -> Ruhe-Uhr, sonst
// die Seite von vorher und der Ruhe-Timer neu. Zuerst die Nacht-Uhr setzen,
// damit showSaver() die zweite Spalte (Kamera) gar nicht erst anmeldet.
function ruheAnwenden(){
  nachtUhrSetzen();
  if(ruheAn()) showSaver(); else { hideSaver(); resetIdle(); }
}
// Ruhemodus an- oder abschalten ({t:"ruhe"}, nach jedem Speichern der Geraete
// an alle Panels: ein gleicher Wert aendert nichts). Mit Ruhemodus haelt ein
// laufender Display-Timer an, ohne gilt wieder die Leerlaufzeit: Nacht-Uhr
// nach NIGHT, Display-Timer neu.
function ruheSetzen(an){
  if(!!an===RUHE) return;
  RUHE=!!an;
  appLeerlauf();
  if(RUHE){ clearTimeout(dpmsTimer); ruheAnwenden(); return; }
  nachtUhrSetzen();
  resetIdle();
}
// Ruhe-Timer abgelaufen (nachRuhe): Mit Ruhemodus entscheidet der Melder,
// die Seite bleibt, wie sie ist. true = nachRuhe() tut nichts weiter.
function ruheNachLeerlauf(){
  if(EINGEBETTET){ eingebettetNachLeerlauf(); return true; }   // Raum-Display-Zelle: Startseite statt Uhr
  if(!RUHE) return false;
  if(ruheAn()) showSaver();
  return true;
}
