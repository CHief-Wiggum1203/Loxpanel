/* LoxPanel Admin-UI Uebersetzung (i18n) fuer /settings und /config.
 *
 * Ansatz: Schluessel = deutscher Quelltext (de ist die Referenz, kein Eintrag
 * noetig). Zusatzsprachen liefern eine Map deutsch->uebersetzt; fehlt ein
 * Eintrag, bleibt der deutsche Text stehen (sichtbarer, aber unschaedlicher
 * Fallback). Gebaeude-/Geraete-/Raum-/Kategorienamen kommen aus dem Miniserver
 * und werden NICHT uebersetzt -> nur explizit markierte Elemente
 * ([data-i18n]) bzw. per T() erzeugte Texte werden angefasst.
 */
(function () {
  var LANGS = [['de', 'Deutsch'], ['en', 'English']];

  var CAT = {
    en: {
      // Rahmen / Navigation
      'Einstellungen': 'Settings',
      'Konfiguration': 'Configuration',
      'Kamera / Türstation': 'Camera / Door station',
      'bald': 'soon',
      'Neues Panel': 'New panel',
      'Sicherung': 'Backup',
      'Einstellungen herunterladen': 'Download settings',
      'Alle Einstellungen dieses Servers als ZIP-Datei: Miniserver-Zugang, Kamera, Kalender, Panels, Geräte und Design.':
        'All settings of this server as a ZIP file: Miniserver access, camera, calendar, panels, devices and design.',
      'Kennwörter (Miniserver, Kamera, Display-Treiber) sind nicht enthalten, weil der Download ohne Anmeldung möglich ist – nach dem Zurückspielen neu eintragen.':
        'Passwords (Miniserver, camera, display driver) are not included because the download needs no login – enter them again after restoring.',
      'Zurückspielen: die Dateien aus dem ZIP in den Config-Ordner legen (Unraid: appdata/loxpanel/config) und LoxPanel neu starten. Das steht auch in der LIESMICH.txt im ZIP.':
        'Restoring: put the files from the ZIP into the config folder (Unraid: appdata/loxpanel/config) and restart LoxPanel. This is also described in LIESMICH.txt inside the ZIP.',
      '＋ Neues Panel': '＋ New panel',
      'Panels & Kacheln': 'Panels & tiles',
      'Ansichten gestalten': 'Design views',
      'Panels · Miniserver · Intercom': 'Panels · Miniserver · Intercom',
      'Visu öffnen': 'Open visu',
      'Panel-Ansicht anzeigen': 'Show panel view',
      // Miniserver
      'Zugang zum Loxone Miniserver. Nach dem Speichern verbindet der Server sofort neu.':
        'Access to the Loxone Miniserver. Reconnects immediately after saving.',
      'Host / IP': 'Host / IP',
      'Benutzer': 'User',
      'Passwort': 'Password',
      'unverändert lassen': 'leave unchanged',
      'Zertifikat prüfen (Gen2 mit selbstsigniertem Zertifikat: aus)':
        'Verify certificate (Gen2 with self-signed cert: off)',
      'Verbinden & Speichern': 'Connect & save',
      // Kamera / Tuerstation
      'Video-URL (MJPEG) und Login der Türstation(en). Wird für das Kamerabild im Intercom-Popup gebraucht. Die Liste kommt aus dem Miniserver.':
        'Video URL (MJPEG) and login of the door station(s). Needed for the camera image in the intercom popup. The list comes from the Miniserver.',
      'Speichern': 'Save',
      'Bausteintypen der Anlage anzeigen': 'Show control types of the installation',
      '(welche Typen vorkommen und welche LoxPanel noch nicht unterstützt; als JSON unter /api/types)':
        '(which types exist and which LoxPanel does not support yet; JSON at /api/types)',
      // SIP
      'Gegensprechen über die Türstation direkt am Panel (SIP-Audio/-Video statt nur Kamerabild).':
        'Two-way audio via the door station directly on the panel (SIP audio/video instead of just the camera image).',
      'SIP-Anbindung ist in Arbeit.': 'SIP integration is in progress.',
      'Coming soon': 'Coming soon',
      // Panels
      'Alle Anzeigegeräte auf einen Blick: Linux-Panels mit Agent melden sich automatisch, Android-Panels und Tablets erscheinen, sobald sie die Visu mit einer Gerätekennung öffnen (?device=<name>). Geräte ohne Kennung stehen unten und bekommen hier einen Namen.':
        'All display devices at a glance: Linux panels with the agent register automatically, Android panels and tablets appear as soon as they open the visu with a device id (?device=<name>). Devices without an id are listed below and get a name here.',
      'Ansicht wechseln': 'Switch view',
      'Neu laden': 'Reload',
      'Display aus': 'Display off',
      'Display an': 'Display on',
      'Visu offen': 'visu open',
      'Ohne Kennung': 'No device id',
      'Gerätename': 'Device name',
      'Namen vergeben': 'Assign name',
      'Bitte einen Namen eingeben': 'Please enter a name',
      'Browser': 'Browser',
      'Ansicht': 'View',
      'Panel nicht erreicht': 'Panel not reached',
      'Geräte ohne Kennung (nach IP). Einen Namen vergeben, damit das Gerät dauerhaft gelistet und per Betriebsmodus umgeschaltet werden kann.':
        'Devices without an id (by IP). Assign a name so the device stays listed and can be switched by operating mode.',
      'Noch kein Panel gefunden. Ein Panel erscheint, sobald es die Visu mit ?device=<name> öffnet oder der Agent darauf läuft.':
        'No panel found yet. A panel appears as soon as it opens the visu with ?device=<name> or the agent runs on it.',
      'Suche Panels…': 'Searching for panels…',
      '(Standard)': '(Default)',
      'Start': 'Start',
      'Reload': 'Reload',
      'Stop': 'Stop',
      'Kiosk läuft': 'Kiosk running',
      'Status:': 'Status:',
      'Video-URL (MJPEG)': 'Video URL (MJPEG)',
      // Audio
      'Der Weckton (Loxone-Wecker) wird direkt im Kiosk-Browser des Panels erzeugt. Mit dem Test-Ton prüfst du, ob am Panel wirklich etwas zu hören ist — falls nicht, liegt es meist an der Lautstärke/Ausgabe am Gerät (ALSA/PulseAudio), nicht am Browser.':
        'The alarm tone (Loxone alarm clock) is generated directly in the panel’s kiosk browser. Use the test tone to check whether the panel actually plays sound — if not, it is usually the volume/output on the device (ALSA/PulseAudio), not the browser.',
      'Test-Ton': 'Test tone',
      'Zonen des Audioservers Gen 2 direkt über Port 7091 steuern (nur Nachbauten wie Sonn oder Audioserver4Home)':
        'Control Audioserver Gen 2 zones directly via port 7091 (only for clones such as Sonn or Audioserver4Home)',
      'Ein mit dem Miniserver gekoppelter Loxone-Audioserver lehnt Befehle ohne Anmeldung ab („command not allowed when paired"). Deshalb gehen Play, Pause, Vor, Zurück und Lautstärke standardmäßig über den Miniserver. Zonen eines Musikservers Gen 1 werden immer direkt gesteuert.':
        'A Loxone Audioserver paired with the Miniserver rejects unauthenticated commands ("command not allowed when paired"). Play, pause, next, previous and volume therefore go through the Miniserver by default. Zones of a Music Server Gen 1 are always controlled directly.',
      'Sendet 3 kurze Pieptöne an das/die gewählte(n) Panel(s). Es müssen dafür geöffnet sein (Kiosk läuft und zeigt die Visu).':
        'Sends 3 short beeps to the selected panel(s). They must be open (kiosk running and showing the visu).',
      'Ziel-Panel': 'Target panel',
      '🔊 Test-Ton senden': '🔊 Send test tone',
      'Alle Panels': 'All panels',
      // Kalender & Wetter (Front / Screensaver)
      'Kalender & Wetter': 'Calendar & weather',
      'Zeigt Termine aus deinen iCal-Abos und das Wetter auf der Uhr-Startseite (Screensaver) aller Panels. Serverweit — der Server holt die Daten und schickt sie an die Panels.':
        'Shows events from your iCal subscriptions and the weather on the clock start page (screensaver) of all panels. Server-wide — the server fetches the data and pushes it to the panels.',
      'iCal-Kalender': 'iCal calendars',
      'Abo-Link aus Apple/iCloud (Kalender → Teilen → Öffentlicher Kalender), Google oder anderen Diensten. webcal:// oder https://. Nur Lesen, kein Login. Mehrere Kalender möglich — Geburtstage, Müllabfuhr, Ferien und die Familientermine landen gemeinsam auf einer Liste.':
        'Subscription link from Apple/iCloud (Calendar → Share → Public calendar), Google or other services. webcal:// or https://. Read-only, no login. Several calendars are possible — birthdays, waste collection, school holidays and family appointments all end up in one list.',
      'Überschrift am Panel': 'Heading on the panel',
      '＋ Kalender hinzufügen': '＋ Add calendar',
      'Feiertags-iCal (optional)': 'Holiday iCal (optional)',
      'z.B. österr. Feiertage aus Google Kalender (basic.ics)':
        'e.g. Austrian public holidays from Google Calendar (basic.ics)',
      'Optionaler zweiter iCal nur für Feiertage — deren Tage werden im Monatsraster rot markiert (wie Sonntage). Z.B. der Feiertagskalender deines Landes aus Google.':
        'An optional second iCal for public holidays only — those days are marked red in the month grid (like Sundays). For example your country’s holiday calendar from Google.',
      // Kalenderzeile
      'Kalender': 'Calendar',
      'Name': 'Name',
      'Farbe': 'Color',
      'Entfernen': 'Remove',
      'iCal-Abo-URL': 'iCal subscription URL',
      'z.B. Müllabfuhr': 'e.g. waste collection',
      'Noch kein Kalender. Mit „＋ Kalender hinzufügen" den ersten Abo-Link eintragen.':
        'No calendar yet. Use “＋ Add calendar” to enter the first subscription link.',
      'Mehr als {max} Kalender gehen nicht.': 'More than {max} calendars are not possible.',
      // Status der Kalender
      'noch nicht geladen': 'not loaded yet',
      'geladen': 'loaded',
      'Termine': 'events',
      'Fehler:': 'Error:',
      'Kalender geladen': 'Calendar loaded',
      'Kein Kalender konfiguriert.': 'No calendar configured.',
      'aus {n} Kalendern': 'from {n} calendars',
      '{n} von {gesamt} Kalendern nicht geladen': '{n} of {gesamt} calendars not loaded',
      'Grund steht oben beim jeweiligen Kalender.':
        'The reason is shown above, at the calendar concerned.',
      'Das Panel zeigt weiter den Stand von {zeit} Uhr.':
        'The panel still shows the data from {zeit}.',
      'Panel zeigt den Stand von {zeit} Uhr.': 'Panel is showing the data from {zeit}.',
      // Wetter
      'Wetter': 'Weather',
      'Verlauf': 'History',
      'Zeitraum': 'Period',
      'Trend': 'Trend',
      'Tagesmuster': 'Daily pattern',
      'Tagesspanne': 'Daily range',
      'Kurve mit Tief, Hoch und Änderung': 'Curve with low, high and change',
      'Verbrauch als Balken, dazu die Summe': 'Consumption as bars, plus the total',
      'Ein/Aus als Stufen, dazu die Einschaltdauer': 'On/off as steps, plus the time switched on',
      '7 Tage × 24 Stunden als Farbraster': '7 days × 24 hours as a color grid',
      'Tief bis Hoch je Tag, 7 Tage': 'Low to high per day, 7 days',
      '7 Tage': '7 days',
      '30 Tage': '30 days',
      'Hat die Anlage den Loxone-Wetterdienst, kommt das Wetter von dort — die Koordinaten bleiben dann unbenutzt. Sonst von Open-Meteo: kostenlos, ohne API-Schlüssel und ohne Konto, nur die Koordinaten deines Standorts eintragen (Dezimalgrad, z.B. 47.071 / 15.439). Leer lassen schaltet das Wetter aus, solange kein Wetterserver liefert.':
        'If the installation has the Loxone weather service, the weather comes from there — the coordinates then stay unused. Otherwise from Open-Meteo: free, no API key and no account, just enter the coordinates of your location (decimal degrees, e.g. 47.071 / 15.439). Leaving them empty switches the weather off, as long as no weather server delivers.',
      'Breitengrad': 'Latitude',
      'Längengrad': 'Longitude',
      'Wetter vom Loxone-Wetterserver': 'Weather from the Loxone weather server',
      'Open-Meteo wird nicht abgefragt.': 'Open-Meteo is not queried.',
      'Wetter geladen': 'Weather loaded',
      'Standort vom Miniserver wird verwendet.': 'The location from the Miniserver is used.',
      'Kein Standort konfiguriert.': 'No location configured.',
      'Automatisch vom Miniserver:': 'Automatically from the Miniserver:',
      // Anzeige am Panel
      'Anzeige': 'Display',
      'Termine der nächsten … Tage': 'Events for the next … days',
      'Wetter-Vorschau (Tage)': 'Weather forecast (days)',
      'Termine auf der Uhr-Seite (max.)': 'Events on the clock page (max.)',
      'Kalenderfarben am Panel zeigen': 'Show calendar colors on the panel',
      'Aus = schlicht: alle Termine einfarbig, nur der Kalendername steht daneben. An = jeder Kalender bekommt seinen Farbpunkt, auch im Monatsraster.':
        'Off = plain: all events in a single color, only the calendar name beside them. On = every calendar gets its color dot, in the month grid too.',
      '„Termine auf der Uhr-Seite" ist eine Obergrenze — was neben Wetter und Uhr nicht mehr auf den Schirm passt, bleibt weg (auf einem 480×480-Panel sind das etwa drei). Die vollständige Liste steht im Kalender-Pane.':
        '“Events on the clock page” is an upper limit — whatever no longer fits on the screen next to the weather and the clock is left out (on a 480×480 panel that is about three). The full list is in the calendar pane.',
      // Neues Panel
      'Neues Panel einrichten': 'Set up a new panel',
      'Erzeugt den Befehl, der Agent + Config aufs Panel überträgt, den Autostart einrichtet und Chromium still stellt (keine Übersetzen-Leiste / Anmeldung). Einmal im Terminal ausführen — fragt nach dem SSH-/sudo-Passwort des Panels.':
        'Generates the command that copies agent + config to the panel, sets up autostart and quiets Chromium (no translate bar / sign-in). Run once in a terminal — it asks for the panel’s SSH/sudo password.',
      'Panel-IP': 'Panel IP',
      'SSH-Benutzer': 'SSH user',
      'Anzeigename': 'Display name',
      'Startansicht (Profil)': 'Start view (profile)',
      'Server-Adresse (dieser Server)': 'Server address (this server)',
      'Befehl erzeugen': 'Generate command',
      'In Zwischenablage kopieren': 'Copy to clipboard',
      'Panel-IP und Server-Adresse nötig': 'Panel IP and server address required',
      '✓ kopiert': '✓ copied',
      'Kopieren nicht möglich – bitte manuell markieren': 'Copy failed – please select manually',
      'Fehler': 'Error',
      'Keine Intercom-Bausteine gefunden (Miniserver verbunden?).':
        'No intercom blocks found (Miniserver connected?).',
      '✓ Gespeichert': '✓ Saved',
      'verbunden': 'connected',
      'nicht verbunden': 'not connected',

      // ---- Betriebsmodus-Automatik (/settings) ----
      'Betriebsmodus-Automatik': 'Operating-mode automation',
      'Loxone schaltet die Ansicht automatisch um: in Loxone Config einen virtuellen HTTP-Ausgang anlegen, der pro Betriebsart einen Modusnamen an diesen Server schickt. Hier legst du je Panel fest, welche Ansicht bei welchem Modus erscheint. Panel ohne Eintrag für einen Modus bleibt unverändert.':
        'Loxone switches the view automatically: in Loxone Config create a virtual HTTP output that sends a mode name to this server per operating mode. Here you define, per panel, which view appears for which mode. A panel without an entry for a mode stays unchanged.',
      'Panels mit Agent (Linux) erscheinen automatisch. Ein Panel ohne Agent (z.B. NSPanel Pro, Tablet) muss nur die Visu mit einer Geräte-Kennung öffnen: ?panel=<start>&device=<name> — dann wird es hier gelistet und live umgeschaltet (Browser lädt sich mit neuem Profil neu, kein Agent nötig).':
        'Panels with an agent (Linux) appear automatically. A panel without an agent (e.g. NSPanel Pro, tablet) just opens the visu with a device id: ?panel=<start>&device=<name> — then it is listed here and switched live (the browser reloads with the new profile, no agent needed).',
      'Noch kein Panel bekannt. Sobald ein Panel die Visu mit Kennung öffnet oder ein Agent läuft, erscheint es hier.':
        'No panel known yet. As soon as a panel opens the visu with a device id or an agent runs, it appears here.',
      'Betriebsmodus-Automatik und Display-Steuerung': 'Operating-mode automation and display control',
      'Display-Steuerung je Gerät: Bei Fully Kiosk die Remote-Admin-Schnittstelle einschalten (Port 2323, Passwort), bei WallPanel den HTTP-Server (Port 2971). Der Server schaltet das Display dann auch bei Klingel, Wecker, Notify und Goto ein und nach der Abschaltzeit aus, unabhängig von der Seite.':
        'Display control per device: for Fully Kiosk enable the Remote Admin interface (port 2323, password), for WallPanel the HTTP server (port 2971). The server then switches the display on for doorbell, alarm clock, notify and goto and off after the timeout, independent of the page.',
      'Display-Steuerung': 'Display control',
      // Skalierung / Bildschirmgroesse
      'Skalierung': 'Scaling',
      'Wie im Profil': 'Same as profile',
      'Aus (feste Größe)': 'Off (fixed size)',
      'Automatisch (Bildschirm ausnutzen)': 'Automatic (use the screen)',
      'Fest': 'Fixed',
      'quer': 'landscape',
      'hoch': 'portrait',
      'quadratisch': 'square',
      'physisch': 'physical',
      'Visu': 'visu',
      'nutzt': 'uses',
      'Skalierung „Automatisch": Jedes Display vergrößert die Visu so weit, wie es ohne Rand und ohne Verzerrung geht – Schrift, Icons, Uhr-Seite und Panes wachsen mit. Ein fester Faktor wird nie größer, als der Bildschirm hergibt. Wirkt nicht zusammen mit „Bildschirm füllen", das den Schirm schon ausfüllt. „Wie global" übernimmt die Einstellung unter Global → Darstellung; pro Gerät übersteuerbar unter Settings → Panels.':
        'Scaling "Automatic": each display enlarges the visu as far as it can without borders or distortion – text, icons, clock page and panes grow along. A fixed factor never exceeds what the screen allows. Has no effect together with "Fill screen", which already fills the screen. "Same as global" takes the setting under Global → Appearance; can be overridden per device under Settings → Panels.',
      'Wie global': 'Same as global',
      'Standard für alle Panels': 'Default for all panels',
      'Automatisch': 'Automatic',
      'Aus': 'Off',
      'Gilt für alle Panels, deren Profil „Wie global" eingestellt hat. „Automatisch" vergrößert die Visu auf jedem Display so weit, wie es ohne Rand und ohne Verzerrung geht. Ein Profil kann das unter Aussehen übersteuern, ein einzelnes Gerät unter Settings → Panels.':
        'Applies to all panels whose profile is set to "Same as global". "Automatic" enlarges the visu on every display as far as it can without borders or distortion. A profile can override this under Appearance, a single device under Settings → Panels.',
      'keine (nur über die Seite)': 'none (page only)',
      'Passwort (Fully)': 'Password (Fully)',
      'Zwei Wege: ein Android-Panel oder Tablet mit Kiosk-App bekommt nur eine Start-URL; ein Linux-Panel bekommt den Agenten per SSH.':
        'Two ways: an Android panel or tablet with a kiosk app only needs a start URL; a Linux panel gets the agent via SSH.',
      'Android-Panel oder Tablet (Kiosk-App)': 'Android panel or tablet (kiosk app)',
      'Start-URL in Fully Kiosk Browser oder WallPanel eintragen. Der Gerätename sorgt dafür, dass das Gerät unter Panels erscheint und per Betriebsmodus umgeschaltet werden kann. Display-Abschaltung: bei Fully die JavaScript-Schnittstelle einschalten oder oben einen Display-Treiber eintragen. Details in deploy/ANDROID.md.':
        'Enter the start URL in Fully Kiosk Browser or WallPanel. The device name makes the device appear under Panels and switchable by operating mode. Display off: enable the JavaScript interface in Fully or configure a display driver above. Details in deploy/ANDROID.md.',
      'Start-URL erzeugen': 'Generate start URL',
      'Gerätename und Server-Adresse nötig': 'Device name and server address required',
      'Linux-Panel mit Agent (SSH)': 'Linux panel with agent (SSH)',
      '— Ansicht wählen —': '— choose view —',
      'Modus (z.B. gaeste)': 'Mode (e.g. guests)',
      'Automatik aktiv': 'Automation active',
      '+ Modus': '+ Mode',
      'Zeile entfernen': 'Remove row',

      // ---- /config (Panel-Editor) ----
      'Konfiguration': 'Configuration',
      '＋ Neues Panel': '＋ New panel',
      'Titel': 'Title',
      'Fenstertitel des Panels.': 'Window title of the panel.',
      'Kiosk-URL:': 'Kiosk URL:',
      'Standard-Aussehen für <b>alle</b> Panels. Einzelne Panels können es unter „Darstellung" überschreiben (leer = erbt global).':
        'Default look for <b>all</b> panels. Individual panels can override it under "Appearance" (empty = inherits global).',
      'Untere Leiste (Tabs)': 'Bottom bar (tabs)',
      'Bis zu <b>4 Buttons</b> — die 4 Standard-Tabs und/oder einzelne Kategorien als Abkürzung. Der <b>erste aktive</b> ist die Startseite (★). ':
        'Up to <b>4 buttons</b> — the 4 standard tabs and/or individual categories as shortcuts. The <b>first active</b> one is the start page (★). ',
      'Räume': 'Rooms',
      'Welche Räume dieses Panel zeigt. <b>Nichts angehakt = alle Räume.</b>':
        'Which rooms this panel shows. <b>Nothing checked = all rooms.</b>',
      'Alle abwählen': 'Deselect all',
      'Kategorien': 'Categories',
      'Welche Kategorien im Tab „Kategorien" erscheinen. <b>Nichts angehakt = alle.</b> Bei gesetzter Raum-Auswahl werden Kategorien zusätzlich auf diese Räume gefiltert.':
        'Which categories appear in the "Categories" tab. <b>Nothing checked = all.</b> If a room selection is set, categories are additionally filtered to those rooms.',
      'Kacheln gestalten': 'Style tiles',
      'Klicke eine Kachel an und ändere <b>Farben, Schrift und Icon nur für diese Kachel</b> (auf diesem Panel). Farbiger Punkt = schon angepasst. Mit dem <b>Auge</b> rechts blendest du eine Kachel auf diesem Panel ganz aus. ':
        'Click a tile and change <b>colors, font and icon for this tile only</b> (on this panel). Colored dot = already customized. Use the <b>eye</b> on the right to hide a tile entirely on this panel. ',
      'Kachel suchen…': 'Search tile…',
      'Darstellung (optional)': 'Appearance (optional)',
      'Überschreibt das globale Theme nur für dieses Panel. Leer = global.':
        'Overrides the global theme for this panel only. Empty = global.',
      'Aktiv-Overlay': 'Active overlay',
      'Wie eine Kachel im <b>aktiven Zustand</b> hervorgehoben wird (an = Akzent, ok = grün, kritisch = rot): Rahmen, Füllung und Deckkraft. Die <b>Farbe</b> kommt je Zustand aus dem Theme, hier stellst du das <b>Aussehen</b> ein. Gilt für dieses Panel — einzelne Kacheln können unten abweichen.':
        'How a tile is highlighted in its <b>active state</b> (on = accent, ok = green, critical = red): border, fill and opacity. The <b>color</b> per state comes from the theme; here you set the <b>look</b>. Applies to this panel — individual tiles can differ below.',
      'Panel löschen': 'Delete panel',
      'Kein Panel gewählt.': 'No panel selected.',
      'keine Kacheln im gewählten Raum-/Kategorie-Filter': 'no tiles in the selected room/category filter',
      'nichts gefunden': 'nothing found',
      // Labels
      'Icon-Größe': 'Icon size',
      'Name-Größe': 'Name size',
      'Sub-Größe': 'Sub size',
      'Schriftart': 'Font',
      'Schriftfarbe (Name)': 'Text color (name)',
      'Sprache': 'Language',
      'Steuert vorerst Datum & Uhr am Panel. Gerätenamen kommen aus dem Miniserver.':
        'For now controls date & clock on the panel. Device names come from the Miniserver.',
      'Horiz. Versatz (px)': 'Horiz. offset (px)',
      'Display aus nach (Sek.)': 'Display off after (sec.)',
      'Auto-Neustart alle (Std.)': 'Auto-restart every (hrs.)',
      'Kacheln pro Zeile': 'Tiles per row',
      'Füllung': 'Fill',
      'Rahmen': 'Border',
      'Rahmenbreite': 'Border width',
      'Darstellung': 'Appearance',
      'Hintergrund': 'Background',
      'Icon-Farbe': 'Icon color',
      'Textfarbe': 'Text color',
      'Schrift': 'Font',
      // Optionen
      'Standard (global)': 'Default (global)',
      'System (Sans)': 'System (Sans)',
      'Eigene…': 'Custom…',
      'Rahmen + Füllung': 'Border + fill',
      'Nur Rahmen': 'Border only',
      'Nur Füllung': 'Fill only',
      '2 × 2 (4″-Panel)': '2 × 2 (4″ panel)',
      '3 × 2 (Tablet)': '3 × 2 (tablet)',
      'Standard (Deutsch)': 'Default (German)',
      // Icon-Reiter / Kachel-Editor
      'Eingebaut': 'Built-in',
      'Google · Upload': 'Google · Upload',
      'Kachel zurücksetzen': 'Reset tile',
      'Standard': 'Default',
      'Alle einblenden': 'Show all',
      'Auf Standard zurücksetzen': 'Reset to default',
      'neutral': 'neutral',
      'Aktiv': 'Active',
      // Global-Editor
      '🌐 Globale Darstellung': '🌐 Global appearance',
      'Schrift, Größe, Farbe und Stärke der Kachel-Beschriftung — gilt global für alle Panels.':
        'Font, size, color and weight of the tile labels — applies globally to all panels.',
      'Kategorie-Farben (Ampel)': 'Category colors (traffic light)',
      'Pro Kategorie eine <b>Aktiv-</b> und <b>OK-Farbe</b> für Kachel-Hintergrund und Rahmen — gilt systemweit auf allen Panels (Wiedererkennung). ◐ einschalten = Zustands-Ampel (z. B. Alarm rot/grün, Tor gelb/grün). Aus = neutral. Analoge Messwerte bleiben immer neutral.':
        'Per category an <b>active</b> and an <b>OK</b> color for tile background and border — applies system-wide on all panels (recognizability). Turn on ◐ = state traffic light (e.g. alarm red/green, gate yellow/green). Off = neutral. Analog readings always stay neutral.',
      // Dialoge
      'ID des neuen Panels (klein, ohne Leerzeichen), z. B. wohnzimmer:':
        'ID of the new panel (lowercase, no spaces), e.g. livingroom:',
      'Ungültige ID.': 'Invalid ID.'
    }
  };

  function detect() {
    try { var s = localStorage.getItem('lp_ui_lang'); if (s && (s === 'de' || CAT[s])) return s; } catch (e) {}
    var n = (navigator.language || 'de').toLowerCase().split('-')[0];
    return (n === 'de' || CAT[n]) ? n : 'de';
  }

  var LANG = detect();

  function T(s) {
    if (s == null) return s;
    if (LANG === 'de') return s;
    var m = CAT[LANG];
    return (m && m[s] != null) ? m[s] : s;
  }

  function apply(root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      var k = el.getAttribute('data-i18n') || el.textContent.trim();
      if (k) el.textContent = T(k);
    });
    root.querySelectorAll('[data-i18n-ph]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-ph') || el.getAttribute('placeholder') || '';
      if (k) el.setAttribute('placeholder', T(k));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-title'); if (k) el.setAttribute('title', T(k));
    });
  }

  function mountSwitcher() {
    var host = document.querySelector('[data-langsel]');
    if (!host) return;
    var sel = document.createElement('select');
    sel.className = 'langsel';
    LANGS.forEach(function (l) {
      var o = document.createElement('option');
      o.value = l[0]; o.textContent = l[1];
      if (l[0] === LANG) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = function () {
      try { localStorage.setItem('lp_ui_lang', sel.value); } catch (e) {}
      location.reload();
    };
    host.appendChild(sel);
  }

  // ---- Auto-Uebersetzer fuer JS-generierte Seiten (z.B. /config) ----
  // Uebersetzt nur BLATT-Elemente (reiner Text, keine Kind-Elemente) der
  // angegebenen Chrome-Selektoren und nur, wenn es eine Uebersetzung gibt
  // (sonst bleibt der deutsche Text). Miniserver-Namen sind nicht im Katalog
  // -> bleiben unangetastet. Reagiert per MutationObserver auf Neu-Rendern.
  var _sel = null, _pending = false;

  function applyChrome(root) {
    if (!_sel) return;
    (root || document).querySelectorAll(_sel).forEach(function (el) {
      if (el.children.length) return;             // nur reine Textknoten
      var k = (el.textContent || '').trim();
      if (!k) return;
      var t = T(k);
      if (t !== k) el.textContent = t;            // nur bei echter Uebersetzung schreiben
    });
  }

  function _schedule() {
    if (_pending) return;
    _pending = true;
    var raf = window.requestAnimationFrame || function (f) { setTimeout(f, 16); };
    raf(function () { _pending = false; applyChrome(document); });
  }

  function autoChrome(selectors) {
    _sel = selectors;
    applyChrome(document);
    try {
      new MutationObserver(_schedule).observe(document.body,
        { childList: true, subtree: true, characterData: true });
    } catch (e) {}
  }

  // Global verfuegbar fuer die Seiten-Skripte (T fuer dynamisch erzeugte Texte).
  window.I18N = { lang: LANG, t: T, apply: apply, applyChrome: applyChrome,
                  autoChrome: autoChrome, langs: LANGS };
  window.T = T;

  document.addEventListener('DOMContentLoaded', function () {
    document.documentElement.setAttribute('lang', LANG);
    mountSwitcher();
    apply(document);
  });
})();
