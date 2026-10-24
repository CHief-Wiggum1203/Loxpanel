'use strict';
/* LoxOS-Huelle (Fork, docs/VISION.md): zeigt die Visu von Loxpanel auf einem
   flachen Streifen-Display.

   Widget-Modus: rahmenloses Vollbild auf dem Streifen. Desktop-Modus: das
   Fenster ist weg, der Streifen ein normaler Bildschirm, die Huelle wartet
   im Tray. Umschalten per Tastenkuerzel (kuerzelModus) oder im Tray.
   Einstellungen in loxos.json im Benutzerordner der App (einstellungen.js);
   fehlt die Adresse von Loxpanel, oeffnet sich zuerst die Einrichtung.

   Sicherheit: das Visu-Fenster ohne Node, isoliert und im Sandbox-Prozess;
   es navigiert nur innerhalb von Loxpanel (gleiche Herkunft), Links nach
   draussen oeffnet der Browser des Systems. Das Mikrofon (Gegensprechen an
   der Tuerstation) bekommt nur Loxpanel. */

const { app, BrowserWindow, Menu, Tray, globalShortcut, ipcMain, nativeImage, screen, session, shell } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const E = require('./einstellungen');
const M = require('./monitor');

const DATEI = () => path.join(app.getPath('userData'), 'loxos.json');
const ICON = path.join(__dirname, '..', 'assets', process.platform === 'darwin' ? 'trayTemplate.png' : 'tray.png');

let werte = null;        // gepruefte Einstellungen
let fenster = null;      // die Visu
let einrichtung = null;  // Fenster der Einrichtung
let tray = null;
let modus = 'widget';

function laden() {
  let roh = {};
  try { roh = JSON.parse(fs.readFileSync(DATEI(), 'utf8')); } catch (e) { roh = {}; }
  const p = E.pruefeEinstellungen(roh, os.hostname());
  if (p.verworfen.length) console.warn('loxos.json: verworfen', p.verworfen.join(', '));
  return p;
}
function speichern(neu) {
  fs.mkdirSync(path.dirname(DATEI()), { recursive: true });
  const tmp = DATEI() + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(neu, null, 2), 'utf8');
  fs.renameSync(tmp, DATEI());
}

// ---- Visu-Fenster --------------------------------------------------------------
function zielMonitor() {
  return M.waehleMonitor(screen.getAllDisplays(), werte.monitor, screen.getPrimaryDisplay().id);
}
function fensterBauen() {
  fenster = new BrowserWindow({
    // Grund bis die Visu da ist: schwarz statt des weissen Standards, sonst
    // blitzt der Streifen beim Start hell auf (die Visu bringt ihre Farben mit)
    show: false, frame: false, backgroundColor: '#000000', autoHideMenuBar: true, skipTaskbar: true,
    title: 'LoxOS',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false },
  });
  const wc = fenster.webContents;
  wc.setWindowOpenHandler(({ url }) => { if (/^https?:/i.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  wc.on('will-navigate', (ev, url) => { if (!E.gleicheHerkunft(werte, url)) { ev.preventDefault(); if (/^https?:/i.test(url)) shell.openExternal(url); } });
  // Laedt Loxpanel nicht (Server neu gestartet, Netz weg): nach einer Pause neu versuchen
  wc.on('did-fail-load', (ev, code, text, url, haupt) => { if (haupt) setTimeout(() => { if (fenster) fenster.loadURL(E.visuAdresse(werte)); }, 5000); });
  fenster.on('closed', () => { fenster = null; });
  fenster.loadURL(E.visuAdresse(werte));
}
function widgetModus() {
  modus = 'widget';
  if (!fenster) fensterBauen();
  const d = zielMonitor();
  if (d) { fenster.setFullScreen(false); fenster.setBounds(d.bounds); }
  fenster.show();
  fenster.setFullScreen(true);
  trayMenu();
}
function desktopModus() {
  modus = 'desktop';
  if (fenster) { fenster.setFullScreen(false); fenster.hide(); }
  trayMenu();
}
function umschalten() { if (modus === 'widget') desktopModus(); else widgetModus(); }

// Bildschirme dazu, weg oder umgestellt: im Widget-Modus neu einpassen
function bildschirmeGeaendert() { if (modus === 'widget' && fenster) widgetModus(); }

// ---- Tray, Kuerzel, Autostart -----------------------------------------------------
function trayMenu() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Widget-Modus (Vollbild auf dem Streifen)', type: 'radio', checked: modus === 'widget', click: widgetModus },
    { label: 'Desktop-Modus (Streifen frei)', type: 'radio', checked: modus === 'desktop', click: desktopModus },
    { type: 'separator' },
    { label: 'Neu laden', enabled: !!fenster, click: () => fenster && fenster.loadURL(E.visuAdresse(werte)) },
    { label: 'Konfigurator öffnen', click: () => shell.openExternal(werte.server + '/config') },
    { label: 'Einstellungen …', click: einrichtungOeffnen },
    { label: 'Mit der Anmeldung starten', type: 'checkbox', checked: werte.autostart,
      click: m => { werte.autostart = m.checked; speichern(werte); autostartSetzen(); } },
    { type: 'separator' },
    { label: 'Beenden', click: () => app.quit() },
  ]));
  tray.setToolTip('LoxOS · ' + werte.geraet + ' · ' + (modus === 'widget' ? 'Widget-Modus' : 'Desktop-Modus'));
}
function kuerzelSetzen() {
  globalShortcut.unregisterAll();
  let ok = false;
  try { ok = globalShortcut.register(werte.kuerzelModus, umschalten); } catch (e) { ok = false; }
  if (!ok && tray) tray.displayBalloon && tray.displayBalloon({ title: 'LoxOS',
    content: 'Das Tastenkürzel ' + werte.kuerzelModus + ' ist schon belegt – in den Einstellungen ein anderes wählen.' });
}
// Ungepackt (npm start) traegt der Autostart sonst nur das nackte Electron
// ein; dann den Pfad der App als Argument mitgeben.
function autostartSetzen() {
  if (process.platform !== 'win32' && process.platform !== 'darwin') return;
  const ort = app.isPackaged ? {} : { path: process.execPath, args: [app.getAppPath()] };
  app.setLoginItemSettings({ openAtLogin: !!werte.autostart, ...ort });
}

// ---- Einrichtung -----------------------------------------------------------------
function einrichtungOeffnen() {
  if (einrichtung) { einrichtung.focus(); return; }
  einrichtung = new BrowserWindow({
    width: 560, height: 640, resizable: false, title: 'LoxOS · Einstellungen', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true,
                      preload: path.join(__dirname, 'einrichtung-preload.js') },
  });
  einrichtung.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  einrichtung.webContents.on('will-navigate', ev => ev.preventDefault());
  einrichtung.on('closed', () => { einrichtung = null; if (!werte.server) app.quit(); });
  einrichtung.loadFile(path.join(__dirname, 'einrichtung.html'));
}
ipcMain.handle('loxos:laden', () => {
  const haupt = screen.getPrimaryDisplay().id;
  return { werte, monitore: screen.getAllDisplays().map(d => ({ id: d.id, name: M.monitorName(d, haupt) })) };
});
ipcMain.handle('loxos:speichern', (ev, roh) => {
  const p = E.pruefeEinstellungen(roh, os.hostname());
  if (p.fehlt.length || p.verworfen.length) return { ok: false, fehlt: p.fehlt, verworfen: p.verworfen };
  const erstesMal = !werte.server;
  werte = p.werte;
  speichern(werte);
  autostartSetzen();
  if (erstesMal) starten(); else { kuerzelSetzen(); if (fenster) fenster.loadURL(E.visuAdresse(werte)); trayMenu(); }
  if (einrichtung) einrichtung.close();
  return { ok: true };
});

// ---- Start -------------------------------------------------------------------------
function starten() {
  if (!tray) { tray = new Tray(nativeImage.createFromPath(ICON)); tray.on('click', umschalten); }
  kuerzelSetzen();
  autostartSetzen();
  if (werte.modus === 'widget') widgetModus(); else desktopModus();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { if (werte && werte.server) widgetModus(); });
  app.whenReady().then(() => {
    // Mikrofon (Gegensprechen) nur fuer Loxpanel, alles andere nicht
    session.defaultSession.setPermissionRequestHandler((wc, recht, antwort, details) =>
      antwort(recht === 'media' && !!werte && E.gleicheHerkunft(werte, details.requestingUrl || wc.getURL())));
    const p = laden();
    werte = p.werte;
    if (process.platform === 'darwin' && app.dock) app.dock.hide();
    screen.on('display-added', bildschirmeGeaendert);
    screen.on('display-removed', bildschirmeGeaendert);
    screen.on('display-metrics-changed', bildschirmeGeaendert);
    if (p.fehlt.length) einrichtungOeffnen(); else starten();
  });
  // Ein geschlossenes Fenster beendet die Huelle nicht: sie lebt im Tray
  app.on('window-all-closed', () => {});
  app.on('will-quit', () => globalShortcut.unregisterAll());
}
