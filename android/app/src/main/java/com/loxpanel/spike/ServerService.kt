package com.loxpanel.spike

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/**
 * Foreground-Service, der den eingebetteten LoxPanel-Server (webvisu.py) startet
 * und am Leben hält. Der echte LoxPanel-Code liegt in den App-Assets und wird
 * beim ersten Start nach filesDir/loxpanel kopiert, dann aus Python importiert.
 */
class ServerService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(1, buildNotification())
        // Nur beim Boot-Start (BootReceiver) soll die App Fully Kiosk selbst
        // hochziehen — nicht, wenn der Nutzer die App manuell öffnet.
        val launchKiosk = intent?.getBooleanExtra("launchKiosk", false) ?: false

        Thread {
            try {
                val appDir = File(filesDir, "loxpanel")
                deployAssets(appDir)

                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(this))
                }
                val res = Python.getInstance().getModule("boot")
                    .callAttr("start_bg", appDir.absolutePath, 8099)
                Log.i("LPSERVER", "boot.start_bg -> $res")

                if (launchKiosk) {
                    // Warten, bis der Server Anfragen beantwortet (~13s Anlauf),
                    // dann Fully Kiosk mit dem Panel starten.
                    Thread.sleep(15000)
                    launchFullyKiosk()
                }
            } catch (e: Throwable) {
                Log.e("LPSERVER", "Serverstart fehlgeschlagen", e)
            }
        }.start()

        return START_STICKY
    }

    private fun launchFullyKiosk() {
        val url = "http://127.0.0.1:8099/?panel=default"
        try {
            val i = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)).apply {
                setClassName("de.ozerov.fully", "de.ozerov.fully.MainActivity")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(i)
            Log.i("LPSERVER", "Fully Kiosk gestartet ($url)")
        } catch (e: Throwable) {
            Log.e("LPSERVER", "Fully-Kiosk-Start fehlgeschlagen", e)
        }
    }

    /**
     * Kopiert den LoxPanel-Code aus den Assets nach filesDir/loxpanel.
     * bin/ und webfrontend/ werden bei jedem Start aufgefrischt (Code-Update),
     * config/ nur beim ersten Mal — damit über /settings gespeicherte Änderungen
     * (Miniserver-Zugang etc.) erhalten bleiben.
     */
    private fun deployAssets(appDir: File) {
        appDir.mkdirs()
        // Nur bei App-Update neu ausrollen: Stempel = Installationszeit der App.
        // Normale Reboots ueberspringen das Kopieren -> schneller Start.
        val stamp = File(appDir, ".assets_version")
        val current = try {
            packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        } catch (e: Exception) { "" }
        val previous = try { if (stamp.exists()) stamp.readText().trim() else "" } catch (e: Exception) { "" }

        if (current != previous || !File(appDir, "bin/webvisu.py").exists()) {
            copyAsset("loxpanel/bin", File(appDir, "bin"))
            copyAsset("loxpanel/webfrontend", File(appDir, "webfrontend"))
            copyAsset("loxpanel/deploy", File(appDir, "deploy"))
            try { stamp.writeText(current) } catch (e: Exception) {}
            Log.i("LPSERVER", "Assets neu ausgerollt (App-Update) unter ${appDir.absolutePath}")
        } else {
            Log.i("LPSERVER", "Assets aktuell - kein Neukopieren (schneller Start)")
        }

        // config nur beim ersten Mal (ueber /settings gespeicherte Zugangsdaten bleiben)
        val cfg = File(appDir, "config")
        if (!cfg.exists()) {
            copyAsset("loxpanel/config", cfg)
        }
    }

    private fun copyAsset(path: String, out: File) {
        val list = try { assets.list(path) } catch (e: Exception) { null }
        if (list == null || list.isEmpty()) {
            // Datei (oder leeres Verzeichnis)
            out.parentFile?.mkdirs()
            try {
                assets.open(path).use { input ->
                    out.outputStream().use { output -> input.copyTo(output) }
                }
            } catch (e: Exception) {
                // war ein (leeres) Verzeichnis — ignorieren
            }
        } else {
            out.mkdirs()
            for (name in list) {
                copyAsset("$path/$name", File(out, name))
            }
        }
    }

    private fun buildNotification(): Notification {
        val channelId = "loxpanel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                channelId, "LoxPanel Server", NotificationManager.IMPORTANCE_LOW
            )
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(ch)
        }
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, channelId) else Notification.Builder(this)
        return builder
            .setContentTitle("LoxPanel Server")
            .setContentText("läuft auf 127.0.0.1:8099")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
    }
}
