package com.loxpanel.spike

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Eingebauter Kiosk: Vollbild-WebView auf den lokalen LoxPanel-Server. Ersetzt
 * Fully Kiosk — die App kontrolliert die Anzeige selbst. Lädt die Panel-URL und
 * lädt bei jedem Fehler (Server noch nicht bereit / neu gestartet) alle 2 s neu.
 *
 * Bildschirmschoner: Nach Inaktivität zeigt die App selbst einen schwarzen
 * Screen mit großer Uhr und dimmt das Backlight auf Minimum. Aufwecken per
 * Berührung ODER — falls ein Näherungssensor vorhanden ist (Shelly Wall Display,
 * Sonoff NSPanel Pro) — per Annäherung. Bewusst NICHT über die Firmware/den
 * Geräteadmin, weil deren Annäherungs-Weckung greift nur, wenn der Hersteller-
 * Launcher im Vordergrund ist — hier ist es unsere Visu.
 */
class KioskActivity : Activity(), SensorEventListener {

    private lateinit var web: WebView
    private lateinit var root: FrameLayout
    private lateinit var saver: View
    private lateinit var clock: TextView
    private val ui = Handler(Looper.getMainLooper())
    private var errored = false
    private var reloadPending = false

    // Bildschirmschoner nach Inaktivität. Die Zeit kommt aus /config ("Display aus
    // nach (Sek.)", Feld dpmsOff) über die JS-Brücke LoxKiosk; bis dahin 90 s als
    // Vorgabe. dpmsOff=0 schaltet den Schoner ab.
    private var idleMs = 90_000L
    private var saverEnabled = true
    private var saverOn = false
    private val goDark = Runnable { enterScreensaver() }
    private val tick = object : Runnable {
        override fun run() { updateClock(); ui.postDelayed(this, 10_000L) }
    }

    private val sensorManager by lazy { getSystemService(Context.SENSOR_SERVICE) as? SensorManager }
    // Näherungssensor (falls vorhanden). Am Shelly ist er ein Wake-up-Sensor, den
    // getDefaultSensor() nicht liefert -> zuerst über getSensorList suchen.
    private val proximity: Sensor? by lazy {
        sensorManager?.let {
            it.getSensorList(Sensor.TYPE_PROXIMITY).firstOrNull()
                ?: it.getDefaultSensor(Sensor.TYPE_PROXIMITY)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Server sicherstellen (idempotent — läuft als Foreground-Service)
        val svc = Intent(this, ServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(svc) else startService(svc)

        // Bildschirm anlassen: Wir dimmen im Screensaver selbst, damit die App
        // aktiv bleibt und den Näherungssensor auswerten kann (sofortiges Wecken).
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#0b1020"))
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false   // Wecker-Ton ohne Nutzergeste
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = false
            displayZoomControls = false
            @Suppress("DEPRECATION")
            textZoom = 100
            cacheMode = WebSettings.LOAD_DEFAULT
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean = false
            override fun onReceivedError(v: WebView, req: WebResourceRequest?, err: WebResourceError?) {
                if (req == null || req.isForMainFrame) { errored = true; scheduleReload() }
            }
            // Jede geladene Visu-Adresse merken (auch nach einem Ansichtswechsel
            // per ?panel=), damit die App nach einem Neustart dort weitermacht.
            override fun onPageFinished(v: WebView, adresse: String?) {
                Visu.merken(this@KioskActivity, adresse)
            }
        }
        // Brücke für die Visu: übergibt die konfigurierte Display-aus-Zeit (dpmsOff
        // aus /config) an den nativen Screensaver.
        web.addJavascriptInterface(KioskBridge(), "LoxKiosk")

        // Screensaver-Overlay: schwarz + große Uhr, zunächst versteckt.
        clock = TextView(this).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 96f)
            gravity = Gravity.CENTER
        }
        saver = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            visibility = View.GONE
            addView(clock, FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        }

        root = FrameLayout(this)
        root.addView(web, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        root.addView(saver, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        setContentView(root)

        show()
        wake()
    }

    /** Lädt die Visu: die zuletzt angezeigte Adresse, sonst das Standardprofil. */
    private fun show() { errored = false; web.loadUrl(Visu.startAdresse(this)) }

    /** Nach 2 s erneut laden (entprellt, wiederholt sich bei anhaltendem Fehler). */
    private fun scheduleReload() {
        if (reloadPending) return
        reloadPending = true
        ui.postDelayed({ reloadPending = false; show() }, 2000)
    }

    override fun onResume() {
        super.onResume()
        enterImmersive()
        // Näherungssensor abonnieren (falls vorhanden) -> weckt aus dem Screensaver.
        // FASTEST für flottes Aufwecken bei Annäherung (Proximity ist on-change +
        // sparsam, daher unkritisch für den Verbrauch).
        proximity?.let { sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_FASTEST) }
        wake()
        if (errored) show()   // beim Zurückkommen sicher neu laden, falls Fehlerzustand
    }

    override fun onPause() {
        super.onPause()
        sensorManager?.unregisterListener(this)
    }

    // Berührung: im dunklen Screensaver weckt sie nur (Tap wird geschluckt, löst
    // keine Kachel aus) und holt den 1. Tab; sonst normal an die Visu weiterreichen.
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (saverOn) { userWake(); return true }
        wake()
        return super.dispatchTouchEvent(ev)
    }

    // Annäherung weckt aus dem dunklen Screensaver und holt den 1. Tab.
    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_PROXIMITY) return
        val near = event.values.isNotEmpty() &&
            event.values[0] < (proximity?.maximumRange ?: 5f)
        if (near && saverOn) userWake()
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) { /* egal */ }

    /** Aus dem Screensaver aufwecken + Inaktivitäts-Timer neu setzen. */
    private fun wake() {
        exitScreensaver()
        rearmIdle()
    }

    /** Aufwecken durch den Nutzer (Berührung/Annäherung) aus dem dunklen Screensaver:
     *  Display an und der Visu sagen, ihre Uhr-Startseite zu schließen -> es steht
     *  der 1. Tab da (den nachRuhe() beim Einschlafen schon gesetzt hat). */
    private fun userWake() {
        wake()
        web.evaluateJavascript("try{ if(typeof wake==='function') wake(); }catch(e){}", null)
    }

    /** Inaktivitäts-Timer neu setzen (nur wenn der Schoner aktiviert ist). */
    private fun rearmIdle() {
        ui.removeCallbacks(goDark)
        if (saverEnabled && !saverOn) ui.postDelayed(goDark, idleMs)
    }

    /** JS-Brücke: die Visu meldet die konfigurierte Display-aus-Zeit (dpmsOff aus
     *  /config). >0 = Schoner nach so vielen Sekunden; 0 = Schoner aus. */
    inner class KioskBridge {
        @JavascriptInterface
        fun setDisplayOff(seconds: Int) {
            ui.post {
                if (seconds > 0) {
                    idleMs = seconds * 1000L
                    saverEnabled = true
                    rearmIdle()
                } else {
                    saverEnabled = false
                    ui.removeCallbacks(goDark)
                    if (saverOn) exitScreensaver()
                }
            }
        }
    }

    /** In den Screensaver gehen: schwarz + Uhr, Backlight auf Minimum. */
    private fun enterScreensaver() {
        if (saverOn) return
        saverOn = true
        updateClock()
        saver.visibility = View.VISIBLE
        saver.bringToFront()
        setBrightness(0f)      // praktisch dunkel (LCD -> kein Einbrennen)
        ui.post(tick)
    }

    /** Screensaver beenden: Visu zeigen, Systemhelligkeit zurück. */
    private fun exitScreensaver() {
        ui.removeCallbacks(tick)
        if (saverOn) {
            saverOn = false
            saver.visibility = View.GONE
        }
        setBrightness(-1f)
    }

    private fun updateClock() {
        clock.text = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date())
    }

    private fun setBrightness(b: Float) {
        val lp = window.attributes
        lp.screenBrightness = b
        window.attributes = lp
    }

    @Suppress("DEPRECATION")
    private fun enterImmersive() {
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION)
    }

    // Kiosk: Zurück-Taste ignorieren, damit man die Anzeige nicht verlässt.
    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() { /* bewusst leer */ }
}
