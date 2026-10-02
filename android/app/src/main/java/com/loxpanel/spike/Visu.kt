package com.loxpanel.spike

import android.content.Context
import java.net.URI
import java.net.URISyntaxException

/**
 * Adresse des eingebetteten LoxPanel-Servers. Port und Start-Adresse stehen nur
 * hier; Server-Dienst, Kiosk-Anzeige und Statusseite lesen sie von hier.
 *
 * Die Kiosk-Anzeige merkt sich die zuletzt geladene Visu-Adresse. Die Visu
 * wechselt eine Ansicht, indem sie sich selbst mit neuem ?panel= lädt (Displays
 * -> Ansicht wechseln, Betriebsmodus-Automatik). Nach einem Neustart der App
 * steht so wieder dieselbe Ansicht da, statt immer das Standardprofil.
 */
object Visu {
    const val PORT = 8099
    const val BASIS = "http://127.0.0.1:$PORT/"

    private const val PREFS = "visu"
    private const val LETZTE = "letzteAdresse"

    /** Zuletzt angezeigte Visu-Adresse, sonst die Visu mit dem Standardprofil. */
    fun startAdresse(ctx: Context): String =
        prefs(ctx).getString(LETZTE, null)?.takeIf { istVisu(it) } ?: BASIS

    /** Merkt sich eine geladene Adresse, wenn sie die Visu selbst ist, nicht
     *  /config oder eine andere Seite des Servers. */
    fun merken(ctx: Context, adresse: String?) {
        if (adresse != null && istVisu(adresse)) {
            prefs(ctx).edit().putString(LETZTE, adresse).apply()
        }
    }

    /** Ob die Adresse die Visu dieses Servers ist: eigener Host und Port, Pfad "/". */
    internal fun istVisu(adresse: String): Boolean {
        if (!adresse.startsWith(BASIS)) return false
        val pfad = try {
            URI(adresse).path
        } catch (e: URISyntaxException) {
            return false
        }
        return pfad.isNullOrEmpty() || pfad == "/"
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
