'use strict';
// Bruecke der Einrichtung: nur Laden und Speichern der Einstellungen, sonst nichts.
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('loxos', {
  laden: () => ipcRenderer.invoke('loxos:laden'),
  speichern: werte => ipcRenderer.invoke('loxos:speichern', werte),
});
