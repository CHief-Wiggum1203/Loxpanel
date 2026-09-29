plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.loxpanel.spike"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.loxpanel.spike"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        // WICHTIG: Für ein echtes ARM-Tablet reicht arm64-v8a. x86_64 nur für den
        // Emulator. Mehr ABIs = längerer Build + größeres APK.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }
}

// ---- Chaquopy: Python einbetten + die kritischen Pakete via pip ----
// Ab Chaquopy 15/16 EIGENER Top-Level-Block (NICHT mehr in android.defaultConfig,
// das war <=14 und verursacht "Unresolved reference: python").
chaquopy {
    defaultConfig {
        version = "3.11"                 // passend zum auf dem PC installierten Python 3.11
        // buildPython nicht gesetzt: Chaquopy nutzt automatisch 'python' vom PATH (muss 3.11 sein)       // Chaquopy nutzt dieses Python zum Bauen reiner sdists
        pip {
            // LoxPanel-Laufzeitabhängigkeiten (webvisu.py + bin/-Module):
            install("cryptography")     // Audioserver-Login (native C-Extension)
            install("aiohttp")          // Webserver + Miniserver-WS
            install("loxone-api")       // Loxone-Client
            install("icalendar")        // Kalender-Front (iCal-Abos)
            install("python-dateutil")  // Serientermine (RRULE)
        }
    }
}

dependencies {
    // bewusst minimal: kein AppCompat nötig, wir nutzen android.app.Activity
}

// ---- LoxPanel-Code IMMER aus dem Repo in die App-Assets synchronisieren ----
// So wird die APK stets aus dem aktuellen Repo-Stand gebaut (keine Handkopie,
// keine Divergenz). Erwartet das Android-Projekt unter <repo>/android/ -> der
// Repo-Wurzelordner ist das Elternverzeichnis der Gradle-Wurzel. config wird OHNE
// echte Zugangsdaten gebuendelt (nur .example/Schema); jeder traegt Miniserver/
// Kamera/Kalender selbst ueber /config bzw. /settings ein.
val loxRepoRoot = rootProject.projectDir.parentFile
tasks.register<Copy>("syncLoxpanelAssets") {
    val dest = layout.projectDirectory.dir("src/main/assets/loxpanel").asFile
    doFirst { dest.deleteRecursively() }
    into(dest)
    from(loxRepoRoot.resolve("bin")) { into("bin") }
    from(loxRepoRoot.resolve("webfrontend")) { into("webfrontend") }
    from(loxRepoRoot.resolve("deploy")) { into("deploy") }
    from(loxRepoRoot.resolve("config")) {
        into("config")
        exclude("loxpanel.cfg", "panels.json", "theme.json")   // keine echten Daten/Layouts
    }
    // Ausserhalb des Repos gebaut -> nicht synchronisieren (vorhandene Assets gelten).
    onlyIf { loxRepoRoot.resolve("bin/webvisu.py").exists() }
}
tasks.named("preBuild") { dependsOn("syncLoxpanelAssets") }
