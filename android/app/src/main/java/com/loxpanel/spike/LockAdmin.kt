package com.loxpanel.spike

import android.app.admin.DeviceAdminReceiver

/**
 * Minimaler Geräteadministrator — nur fuer force-lock, damit die App das Display
 * bei Inaktivitaet echt abschalten kann (DevicePolicyManager.lockNow()).
 * Aktivierung ohne Nutzerdialog per adb:
 *   adb shell dpm set-active-admin com.loxpanel.spike/.LockAdmin
 */
class LockAdmin : DeviceAdminReceiver()
