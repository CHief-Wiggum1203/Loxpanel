package com.loxpanel.spike

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Welche Adressen sich die Kiosk-Anzeige als Start-Adresse merkt. */
class VisuTest {

    @Test
    fun visuMitUndOhneProfil() {
        assertTrue(Visu.istVisu(Visu.BASIS))
        assertTrue(Visu.istVisu(Visu.BASIS + "?panel=wohnen"))
        assertTrue(Visu.istVisu(Visu.BASIS + "?panel=wohnen&device=k%C3%BCche"))
        assertTrue(Visu.istVisu(Visu.BASIS + "#oben"))
    }

    @Test
    fun andereSeitenDesServersNicht() {
        assertFalse(Visu.istVisu(Visu.BASIS + "config"))
        assertFalse(Visu.istVisu(Visu.BASIS + "settings?x=1"))
        assertFalse(Visu.istVisu(Visu.BASIS + "api/meta"))
    }

    @Test
    fun fremdeAdressenNicht() {
        assertFalse(Visu.istVisu("http://10.0.0.5:${Visu.PORT}/?panel=wohnen"))
        assertFalse(Visu.istVisu("http://127.0.0.1:${Visu.PORT + 1}/"))
        assertFalse(Visu.istVisu("http://127.0.0.1:${Visu.PORT}0/"))
        assertFalse(Visu.istVisu("about:blank"))
        assertFalse(Visu.istVisu(""))
    }

    @Test
    fun kaputteAdresseNicht() {
        assertFalse(Visu.istVisu(Visu.BASIS + "?panel=a b"))
    }
}
