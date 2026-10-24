'use strict';
/* LoxOS-Huelle: Einstellungen (loxos.json im Benutzerordner der App) laden und
   pruefen. Reine Logik ohne Electron, getestet mit node --test.

   Felder:
     server        Adresse von Loxpanel (http/https, ohne Zugangsdaten). Pflicht;
                   fehlt sie, oeffnet die Huelle die Einrichtung.
     geraet        Name, unter dem sich die Huelle bei Loxpanel meldet
                   (?device=). Standard: der Rechnername.
     monitor       "auto" (der Streifen: breitestes Seitenverhaeltnis ab
                   STREIFEN_AB) oder {breite, hoehe} bzw. {id}.
     modus         Start im "widget"-Modus (Vollbild auf dem Streifen) oder im
                   "desktop"-Modus (Huelle im Tray, Streifen frei).
     kuerzelModus  Tastenkuerzel zum Umschalten (Electron-Accelerator).
     autostart     mit der Anmeldung starten.
     bildschirmWach  verhindert im Widget-Modus, dass der Energiesparplan des
                   PCs die Bildschirme abschaltet (Standard: an).
   Unbekannte oder ungueltige Felder fallen weg und werden gemeldet. */

const STANDARD = Object.freeze({
  server: '',
  monitor: 'auto',
  modus: 'widget',
  kuerzelModus: 'CommandOrControl+Alt+L',
  autostart: true,
  bildschirmWach: true,
});
const MODI = ['widget', 'desktop'];
const GERAET_MAX = 40;
const KUERZEL_MAX = 60;
const SERVER_MAX = 2000;

// Adresse von Loxpanel: dieselbe Regel wie fuer Webseiten-Zellen
// (bento_format._clean_iframe_url) - nur http/https mit Host, ohne
// Zugangsdaten. -> Adresse ohne Schraegstrich am Ende oder ''.
function pruefeServer(v) {
  if (typeof v !== 'string') return '';
  const u = v.trim();
  if (!u || u.length > SERVER_MAX || /[\s\x00-\x1f\x7f]/.test(u) || !/^https?:\/\/[^/?#]/i.test(u)) return '';
  let t;
  try { t = new URL(u); } catch (e) { return ''; }
  if ((t.protocol !== 'http:' && t.protocol !== 'https:') || !t.hostname || t.username || t.password) return '';
  return (t.origin + t.pathname).replace(/\/+$/, '');
}

// Geraetename: Buchstaben, Ziffern, Leerzeichen, Punkt, Unterstrich, Bindestrich
function pruefeGeraet(v) {
  if (typeof v !== 'string') return '';
  const n = v.trim().slice(0, GERAET_MAX);
  return /^[\p{L}\p{N} ._-]+$/u.test(n) ? n : '';
}
// Rechnername als Geraetename (unerlaubte Zeichen werden zu Bindestrichen)
function geraetAusRechner(rechner) {
  const n = String(rechner || '').replace(/[^\p{L}\p{N} ._-]+/gu, '-').replace(/^-+|-+$/g, '').slice(0, GERAET_MAX);
  return n;
}

function pruefeMonitor(v) {
  if (v === 'auto') return 'auto';
  if (v && typeof v === 'object') {
    const ganz = x => Number.isInteger(x) && x > 0;
    if (Number.isInteger(v.id)) return { id: v.id };
    if (ganz(v.breite) && ganz(v.hoehe)) return { breite: v.breite, hoehe: v.hoehe };
  }
  return null;
}

function pruefeKuerzel(v) {
  if (typeof v !== 'string') return '';
  const k = v.trim();
  return (k && k.length <= KUERZEL_MAX && /^[A-Za-z0-9]+(\+[A-Za-z0-9]+)+$/.test(k)) ? k : '';
}

/* roh: gelesener Inhalt (Objekt), rechner: os.hostname() fuer den Standardnamen.
   -> {werte, verworfen: [Feldname], fehlt: [Pflichtfeld]} */
function pruefeEinstellungen(roh, rechner) {
  const r = (roh && typeof roh === 'object' && !Array.isArray(roh)) ? roh : {};
  const werte = { ...STANDARD, geraet: geraetAusRechner(rechner) };
  const verworfen = [];
  const pruefer = {
    server: pruefeServer, geraet: pruefeGeraet, monitor: pruefeMonitor, kuerzelModus: pruefeKuerzel,
    modus: v => (MODI.includes(v) ? v : ''),
    autostart: v => (typeof v === 'boolean' ? v : null),
    bildschirmWach: v => (typeof v === 'boolean' ? v : null),
  };
  for (const k of Object.keys(r)) {
    if (!(k in pruefer)) { verworfen.push(k); continue; }
    const v = pruefer[k](r[k]);
    if (v === '' || v === null) { if (r[k] !== '' && r[k] !== null) verworfen.push(k); continue; }
    werte[k] = v;
  }
  const fehlt = [];
  if (!werte.server) fehlt.push('server');
  if (!werte.geraet) fehlt.push('geraet');
  return { werte, verworfen, fehlt };
}

// Soll die Huelle die Bildschirme wach halten? Nur im Widget-Modus: im
// Desktop-Modus zeigt der Streifen keine Visu, der PC darf sparen.
function wachHalten(werte, modus) {
  return !!werte.bildschirmWach && modus === 'widget';
}

// Adresse der Visu fuer dieses Geraet
function visuAdresse(werte) {
  return werte.server + '/?device=' + encodeURIComponent(werte.geraet);
}
// Gehoert eine Adresse zu Loxpanel (gleiche Herkunft)? Nur dorthin darf das
// Fenster navigieren; alles andere geht in den Browser des Systems.
function gleicheHerkunft(werte, adresse) {
  try { return new URL(adresse).origin === new URL(werte.server).origin; } catch (e) { return false; }
}

module.exports = {
  STANDARD, MODI, GERAET_MAX, KUERZEL_MAX, SERVER_MAX,
  pruefeServer, pruefeGeraet, geraetAusRechner, pruefeMonitor, pruefeKuerzel,
  pruefeEinstellungen, wachHalten, visuAdresse, gleicheHerkunft,
};
