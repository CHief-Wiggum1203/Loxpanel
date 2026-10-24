'use strict';
/* Einrichtung der LoxOS-Huelle: Formular fuellen, beim Speichern prueft der
   Hauptprozess (einstellungen.js) und meldet, was fehlt oder ungueltig ist. */
const $ = id => document.getElementById(id);
const FELD_FEHLER = { server: 'server-fehler', geraet: 'geraet-fehler', kuerzelModus: 'kuerzel-fehler' };

async function fuellen() {
  const { werte, monitore } = await window.loxos.laden();
  $('server').value = werte.server;
  $('geraet').value = werte.geraet;
  $('kuerzel').value = werte.kuerzelModus;
  $('widget').checked = werte.modus === 'widget';
  $('autostart').checked = werte.autostart;
  const sel = $('monitor');
  const auto = document.createElement('option');
  auto.value = 'auto'; auto.textContent = 'Automatisch (der Streifen)';
  sel.append(auto);
  for (const m of monitore) {
    const o = document.createElement('option');
    o.value = String(m.id); o.textContent = m.name;
    sel.append(o);
  }
  sel.value = (werte.monitor && werte.monitor.id !== undefined) ? String(werte.monitor.id) : 'auto';
}

$('form').addEventListener('submit', async ev => {
  ev.preventDefault();
  for (const id of Object.values(FELD_FEHLER)) $(id).hidden = true;
  $('meldung').hidden = true;
  const m = $('monitor').value;
  const antwort = await window.loxos.speichern({
    server: $('server').value, geraet: $('geraet').value, kuerzelModus: $('kuerzel').value,
    modus: $('widget').checked ? 'widget' : 'desktop', autostart: $('autostart').checked,
    monitor: m === 'auto' ? 'auto' : { id: Number(m) },
  });
  if (antwort.ok) return;
  const falsch = [...antwort.fehlt, ...antwort.verworfen];
  for (const f of falsch) if (FELD_FEHLER[f]) $(FELD_FEHLER[f]).hidden = false;
  $('meldung').textContent = 'Nicht gespeichert – bitte die markierten Angaben prüfen.';
  $('meldung').hidden = false;
});

fuellen();
