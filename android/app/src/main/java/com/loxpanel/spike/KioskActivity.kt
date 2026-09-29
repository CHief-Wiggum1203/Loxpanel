package com.loxpanel.spike

import android.annotation.SuppressLint
import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * Eingebauter Kiosk: Vollbild-WebView auf den lokalen LoxPanel-Server. Ersetzt
 * Fully Kiosk — die App kontrolliert die Anzeige selbst. Lädt die Panel-URL und
 * lädt bei jedem Fehler (Server noch nicht bereit / neu gestartet) alle 2 s neu,
 * bis es klappt. Bildschirm bleibt an, immersiv (System-Leisten aus).
 */
class KioskActivity : Activity() {

    private lateinit var web: WebView
    private val ui = Handler(Looper.getMainLooper())
    private val url = "http://127.0.0.1:8099/?panel=default"
    private var errored = false
    private var reloadPending = false

    // Display-Abschaltung bei Inaktivitaet (Berührung weckt wieder).
    private val idleMs = 90_000L
    private val goDark = Runnable { screenOff() }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Server sicherstellen (idempotent — läuft als Foreground-Service)
        val svc = Intent(this, ServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(svc) else startService(svc)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#0b1020"))
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false
        setContentView(web)

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
                // Nur echte Hauptseiten-Fehler (Server noch/again nicht da) -> neu versuchen
                if (req == null || req.isForMainFrame) { errored = true; scheduleReload() }
            }
        }
        show()
        wake()
    }

    /** Lädt die Panel-URL neu. */
    private fun show() { errored = false; web.loadUrl(url) }

    /** Nach 2 s erneut laden (entprellt, wiederholt sich bei anhaltendem Fehler). */
    private fun scheduleReload() {
        if (reloadPending) return
        reloadPending = true
        ui.postDelayed({ reloadPending = false; show() }, 2000)
    }

    override fun onResume() {
        super.onResume()
        enterImmersive()
        wake()
        if (errored) show()   // beim Zurückkommen sicher neu laden, falls Fehlerzustand
    }

    // Jede Berührung weckt den Bildschirm und startet den Inaktivitäts-Timer neu.
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        wake()
        return super.dispatchTouchEvent(ev)
    }

    /** Bildschirm an (Systemhelligkeit) + Abschalt-Timer neu setzen. */
    private fun wake() {
        setBrightness(-1f)
        ui.removeCallbacks(goDark)
        ui.postDelayed(goDark, idleMs)
    }

    /** Display echt abschalten (lockNow); Fingerberührung weckt wieder.
     *  Ohne Geräteadministrator Fallback auf Dimmen (Helligkeit 0). */
    private fun screenOff() {
        try {
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (dpm.isAdminActive(ComponentName(this, LockAdmin::class.java))) {
                dpm.lockNow()
                return
            }
        } catch (e: Exception) { /* Fallback unten */ }
        setBrightness(0f)
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
