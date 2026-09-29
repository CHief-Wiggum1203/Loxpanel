package com.loxpanel.spike

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.ScrollView
import android.widget.TextView

/**
 * Startet den LoxPanel-Server-Service und zeigt einen kurzen Status.
 * Die eigentliche Anzeige des Panels macht Fully Kiosk auf 127.0.0.1:8099.
 */
class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val intent = Intent(this, ServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }

        val tv = TextView(this).apply {
            textSize = 14f
            setPadding(32, 32, 32, 32)
            gravity = Gravity.TOP or Gravity.START
            text = buildString {
                appendLine("LoxPanel-Server wird gestartet …")
                appendLine()
                appendLine("Fully Kiosk auf:")
                appendLine("    http://127.0.0.1:8099")
                appendLine()
                appendLine("Konfiguration:")
                appendLine("    http://127.0.0.1:8099/config")
                appendLine()
                appendLine("Log ansehen:")
                appendLine("    adb logcat -s LPSERVER python.stdout python.stderr")
            }
        }
        setContentView(ScrollView(this).apply { addView(tv) })
    }
}
