'use strict';
// LoxOS-Huelle: Wahl des Bildschirms (src/monitor.js)
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../src/monitor');

const d = (id, w, h) => ({ id, bounds: { x: 0, y: 0, width: w, height: h } });
const HAUPT = d(1, 2560, 1440), STREIFEN = d(2, 2560, 720), BREIT = d(3, 3440, 1440), FLACH = d(4, 1920, 480);

test('auto: der flachste Streifen, sonst der Hauptbildschirm', () => {
  assert.equal(M.waehleMonitor([HAUPT, STREIFEN, BREIT], 'auto', 1), STREIFEN);
  assert.equal(M.waehleMonitor([HAUPT, STREIFEN, FLACH], 'auto', 1), FLACH, '4:1 vor 32:9');
  assert.equal(M.waehleMonitor([BREIT, HAUPT], 'auto', 1), HAUPT, '21:9 ist kein Streifen');
  assert.equal(M.waehleMonitor([BREIT], 'auto', 1), BREIT, 'ohne Hauptbildschirm der erste');
});

test('feste Wahl nach Groesse oder Kennung, fehlt sie: auto', () => {
  assert.equal(M.waehleMonitor([HAUPT, STREIFEN, FLACH], { breite: 2560, hoehe: 720 }, 1), STREIFEN);
  assert.equal(M.waehleMonitor([HAUPT, STREIFEN], { id: 1 }, 1), HAUPT);
  assert.equal(M.waehleMonitor([HAUPT, STREIFEN], { id: 9 }, 1), STREIFEN);
});

test('keine oder kaputte Bildschirme', () => {
  assert.equal(M.waehleMonitor([], 'auto', 1), null);
  assert.equal(M.waehleMonitor(null, 'auto', 1), null);
  assert.equal(M.waehleMonitor([{ id: 5, bounds: { width: 10, height: 0 } }], 'auto', 1), null);
});

test('Beschriftung nennt Groesse, Hauptbildschirm und Streifen', () => {
  assert.equal(M.monitorName(STREIFEN, 1), '2560 × 720 · Streifen');
  assert.equal(M.monitorName(HAUPT, 1), '2560 × 1440 (Hauptbildschirm)');
});
