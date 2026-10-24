'use strict';
/* LoxOS-Huelle: auf welchem Monitor steht die Visu? Reine Logik ohne
   Electron (Bildschirme wie screen.getAllDisplays(): {id, bounds}).

   "auto": der Bildschirm mit dem breitesten Seitenverhaeltnis, sofern er ein
   Streifen ist (ab STREIFEN_AB, 32:9 = 3,56, 4:1 = 4); ohne Streifen der
   Hauptbildschirm. {breite, hoehe}: der Bildschirm genau dieser Groesse,
   {id}: dieser Bildschirm; gibt es ihn (gerade) nicht, gilt "auto". */

// Ab diesem Verhaeltnis Breite : Hoehe ist ein Bildschirm ein Streifen.
// 21:9-Monitore (2,33) zaehlen nicht, 2560 x 720 (3,56) und 1920 x 480 (4) schon.
const STREIFEN_AB = 2.5;

function verhaeltnis(d) { return d.bounds.width / d.bounds.height; }

function waehleMonitor(bildschirme, wahl, hauptId) {
  const l = Array.isArray(bildschirme) ? bildschirme.filter(d => d && d.bounds && d.bounds.height > 0) : [];
  if (!l.length) return null;
  if (wahl && typeof wahl === 'object') {
    const t = ('id' in wahl) ? l.find(d => d.id === wahl.id)
      : l.find(d => d.bounds.width === wahl.breite && d.bounds.height === wahl.hoehe);
    if (t) return t;
  }
  const streifen = l.filter(d => verhaeltnis(d) >= STREIFEN_AB).sort((a, b) => verhaeltnis(b) - verhaeltnis(a));
  return streifen[0] || l.find(d => d.id === hauptId) || l[0];
}

// Beschriftung fuer die Einrichtung
function monitorName(d, hauptId) {
  return d.bounds.width + ' × ' + d.bounds.height + (d.id === hauptId ? ' (Hauptbildschirm)' : '') +
    (verhaeltnis(d) >= STREIFEN_AB ? ' · Streifen' : '');
}

module.exports = { STREIFEN_AB, waehleMonitor, monitorName };
