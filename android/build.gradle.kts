// Root-Build. Plugin-Versionen zentral, hier nur deklariert (apply false).
// Wenn Gradle-Sync über Versionskonflikte meckert: zuerst diese drei anpassen.
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("com.chaquo.python") version "16.0.0" apply false
}
