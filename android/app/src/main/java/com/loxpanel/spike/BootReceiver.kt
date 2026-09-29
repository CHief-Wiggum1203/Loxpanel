package com.loxpanel.spike

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Startet den Server-Service automatisch nach dem Booten — damit das Panel nach
 * Stromausfall von selbst wieder läuft (Appliance-Verhalten).
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == Intent.ACTION_LOCKED_BOOT_COMPLETED
        ) {
            val svc = Intent(context, ServerService::class.java)
                .putExtra("launchKiosk", true)   // beim Boot: Fully Kiosk mitstarten
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(svc)
            } else {
                context.startService(svc)
            }
        }
    }
}
