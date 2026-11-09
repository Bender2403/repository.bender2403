# Kodi-Logdatei-Uploader – eigenständige GitHub-Version

Diese eigenständige Version basiert auf Ronies Add-on `script.kodi.loguploader` und steht unter der Lizenz GPL-2.0-only. Sie verwendet die eigene Add-on-ID `script.kodi.loguploader.github` und wird deshalb von Kodi getrennt vom Original verwaltet.

**Anzeigename:** Kodi Logfile Uploader (GitHub)  
**Add-on-ID:** `script.kodi.loguploader.github`  
**Version:** `0.0.8`  

**GitHub ist das voreingestellte Upload-Ziel.** Der bisherige Dienst `paste.kodi.tv` bleibt als alternative Upload-Möglichkeit erhalten.

## Installation in Kodi

1. Lade die ZIP-Datei des Add-ons herunter und installiere sie in Kodi über **Aus ZIP-Datei installieren**. Achte darauf, dass die ZIP-Datei den Add-on-Ordner `script.kodi.loguploader.github` enthält.
2. Öffne anschließend die Einstellungen des Add-ons **Kodi Logfile Uploader**.
3. Erstelle auf GitHub ein Fine-grained Personal Access Token.
4. Beschränke das Token auf das Repository `Bender2403/kodi-rakuten-tv-addon`.
5. Erteile dem Token für dieses Repository die Berechtigung **Contents: Read and write**.
6. Trage das Token in das Feld **GitHub Fine-grained Token** ein.
7. Lass die folgenden Standardwerte unverändert:
   - Upload-Ziel: **GitHub (Standard)**
   - GitHub-Repository: `Bender2403/kodi-rakuten-tv-addon`
   - GitHub-Branch: `kodi-logs`

## So funktioniert der Upload

Beim Start erscheint direkt das Hauptmenü. Über den Menüpunkt **Add-ons zur Protokollpriorisierung auswählen** kannst du festlegen, für welche aktivierten Add-ons Logmeldungen bei der Diagnose bevorzugt werden. Deaktivierte Add-ons werden nicht angezeigt. Die Auswahl wird gespeichert und kann jederzeit über diesen Menüpunkt geändert werden. Nach dem Bestätigen kehrt das Add-on automatisch zum Hauptmenü zurück.

Große Logs bis 10 MiB werden eingelesen. Fehler, Warnungen, Tracebacks, Meldungen der ausgewählten Add-ons und der jeweilige Kontext werden bevorzugt. Wiederholte identische Meldungen werden zusammengefasst. Bereinigte Originale werden zusätzlich beigelegt, sofern sie höchstens 2 MiB groß sind.

Unter den Add-on-Einstellungen lässt sich außerdem die **eigene Debug-Protokollierung** ein- und ausschalten. Sie ist unabhängig vom globalen Kodi-Debug-Modus und verändert dessen Einstellung nicht.

Bekannte Zugangsdaten und sensible URL-Parameter werden vor dem Upload bereinigt. Das Add-on verändert die lokale Original-Logdatei nicht.

Jede Logdatei erhält einen Zeitstempel in UTC als Dateinamen, zum Beispiel:

`logs/kodi-20261106T183000Z.log`

Wenn du stattdessen den ursprünglichen Upload-Dienst verwenden möchtest, kannst du in den Add-on-Einstellungen unter **Upload-Ziel** die Option **paste.kodi.tv** auswählen.

## Automatische Löschung nach 60 Minuten

Ein GitHub-Actions-Workflow im Branch `main` überprüft alle 15 Minuten den Branch `kodi-logs`. Logdateien, deren Zeitstempel älter als 60 Minuten ist, werden aus dem aktuellen Stand des Branches gelöscht.

Die Ausführung geplanter GitHub-Actions-Workflows kann sich verzögern. Die Löschung erfolgt daher nicht garantiert exakt nach 60 Minuten.

**Wichtiger Hinweis:** Das Löschen einer Datei aus dem aktuellen Branch entfernt sie nicht aus der Git-Commit-Historie. Frühere Versionen können dort weiterhin vorhanden sein.

## Herkunft und Lizenz

Dieses Add-on ist eine modifizierte, eigenständig installierbare Version von Ronies `script.kodi.loguploader`.

- Originalprojekt: https://gitlab.com/ronie/script.kodi.loguploader/
- Verwendeter Quellstand: `b989e18b4da200a13d4154cc652aa358f534012d`
- Lizenz: GPL-2.0-only
