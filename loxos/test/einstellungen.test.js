'use strict';
// LoxOS-Huelle: Einstellungen pruefen (src/einstellungen.js)
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../src/einstellungen');

test('Adresse: nur http/https mit Host, ohne Zugangsdaten, ohne Schraegstrich am Ende', () => {
  assert.equal(E.pruefeServer('http://192.168.1.10:8080/'), 'http://192.168.1.10:8080');
  assert.equal(E.pruefeServer(' https://loxpanel.local '), 'https://loxpanel.local');
  assert.equal(E.pruefeServer('https://haus.example/loxpanel/'), 'https://haus.example/loxpanel');
  assert.equal(E.pruefeServer('HTTP://Host:80'), 'http://host');
  for (const falsch of ['ftp://host', 'javascript:alert(1)', 'file:///etc', '//host', 'host:8080', 'https://',
                        'http:///pfad', 'https://user:pw@host', 'https://user@host', 'http://ho st', 'http://ho\nst',
                        'https://' + 'a'.repeat(E.SERVER_MAX), '', null, 3, ['http://host']])
    assert.equal(E.pruefeServer(falsch), '', String(falsch));
});

test('Geraetename: erlaubte Zeichen, sonst leer; aus dem Rechnernamen abgeleitet', () => {
  assert.equal(E.pruefeGeraet(' streifen-pc '), 'streifen-pc');
  assert.equal(E.pruefeGeraet('Büro 2'), 'Büro 2');
  assert.equal(E.pruefeGeraet('a/b'), '');
  assert.equal(E.pruefeGeraet('x'.repeat(E.GERAET_MAX + 5)).length, E.GERAET_MAX);
  assert.equal(E.geraetAusRechner('DESKTOP-ABC#1'), 'DESKTOP-ABC-1');
  assert.equal(E.geraetAusRechner('Erichs MacBook.local'), 'Erichs MacBook.local');
});

test('Monitor: auto, Groesse oder Kennung', () => {
  assert.equal(E.pruefeMonitor('auto'), 'auto');
  assert.deepEqual(E.pruefeMonitor({ breite: 2560, hoehe: 720, x: 1 }), { breite: 2560, hoehe: 720 });
  assert.deepEqual(E.pruefeMonitor({ id: 7 }), { id: 7 });
  for (const falsch of [{ breite: 0, hoehe: 720 }, { breite: '2560', hoehe: 720 }, 'links', null, 5])
    assert.equal(E.pruefeMonitor(falsch), null);
});

test('Tastenkuerzel: Tasten mit + verbunden', () => {
  assert.equal(E.pruefeKuerzel('CommandOrControl+Alt+L'), 'CommandOrControl+Alt+L');
  for (const falsch of ['L', 'Ctrl+', '+L', 'Ctrl Alt L', '', 'Ctrl+' + 'A'.repeat(E.KUERZEL_MAX)])
    assert.equal(E.pruefeKuerzel(falsch), '', falsch);
});

test('Ganze Einstellungen: Standard, Pflichtfelder, Verworfenes', () => {
  const leer = E.pruefeEinstellungen(undefined, 'streifen-pc');
  assert.deepEqual(leer.werte, { ...E.STANDARD, geraet: 'streifen-pc' });
  assert.deepEqual(leer.fehlt, ['server']);
  const p = E.pruefeEinstellungen({ server: 'http://lp:8080', geraet: 'Streifen', monitor: { breite: 2560, hoehe: 720 },
                                    modus: 'desktop', autostart: false, unbekannt: 1, kuerzelModus: 'L' }, 'pc');
  assert.deepEqual(p.werte, { server: 'http://lp:8080', geraet: 'Streifen', monitor: { breite: 2560, hoehe: 720 },
                              modus: 'desktop', autostart: false, kuerzelModus: E.STANDARD.kuerzelModus });
  assert.deepEqual(p.verworfen.sort(), ['kuerzelModus', 'unbekannt']);
  assert.deepEqual(p.fehlt, []);
  assert.deepEqual(E.pruefeEinstellungen([], 'pc').fehlt, ['server']);
});

test('Adresse der Visu und gleiche Herkunft', () => {
  const w = { server: 'http://lp:8080', geraet: 'Büro 2' };
  assert.equal(E.visuAdresse(w), 'http://lp:8080/?device=B%C3%BCro%202');
  assert.ok(E.gleicheHerkunft(w, 'http://lp:8080/config'));
  assert.ok(!E.gleicheHerkunft(w, 'http://lp:9090/'));
  assert.ok(!E.gleicheHerkunft(w, 'https://lp:8080/'));
  assert.ok(!E.gleicheHerkunft(w, 'kaputt'));
});
