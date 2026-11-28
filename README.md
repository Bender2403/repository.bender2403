# Kodi-Repository von Bender2403

Dieses öffentliche Repository stellt geprüfte Add-ons für Kodi bereit.

## Repository in Kodi installieren
Repository-ZIP:
`https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/repository.bender2403/repository.bender2403-1.0.3.zip`

Repository-Metadaten:
- `https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/addons.xml`
- `https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/addons.xml.md5`

## Automatische Veröffentlichung und Updates

Die Quellordner liegen unter `addons/<addon-id>/`. Bei jedem Push nach `main` baut GitHub Actions automatisch die zentrale `addons.xml`, die Prüfsumme und die ZIP-Pakete. Generierte Add-on-Verzeichnisse werden direkt im Hauptbranch aktualisiert.

Neue Add-ons können alternativ als ZIP-Datei über den Eingangsordner bereitgestellt werden:

- `arbeitsordner/eingang/`: Hier neue Add-on-ZIPs ablegen.
- `arbeitsordner/quarantaene/`: Fehlerhafte, unsichere oder kollidierende ZIPs werden hierhin verschoben. Für jeden Fehler wird ein Textbericht `<addon-id>.txt` erstellt. Ist keine Add-on-ID lesbar, dient der ZIP-Dateiname ohne Endung als Berichtsname. Mehrere Fehler derselben Add-on-ID werden im selben Bericht gesammelt.

Jede ZIP wird einzeln geprüft. Fehlerhafte Dateien stoppen die Verarbeitung der übrigen ZIPs nicht. Gültige ZIPs werden übernommen und nach erfolgreicher Veröffentlichung aus dem Eingangsordner entfernt. ZIPs mit doppelter Add-on-ID oder einer ID, die bereits unter `addons/` existiert, werden in Quarantäne verschoben.

## Aufbau

- `addons/`: Quellordner der regulären Kodi-Add-ons
- `arbeitsordner/eingang/`: Eingangsordner für Add-on-ZIPs
- `arbeitsordner/quarantaene/`: Fehlerhafte ZIPs samt Fehlerbericht
- `scripts/build_repo.py`: Baut Repository-Metadaten und verarbeitet ZIP-Eingänge
- `scripts/zip_safety.py`: Sicherheitsprüfung und sicheres Entpacken
- `.github/workflows/publish.yml`: Automatischer Build und Veröffentlichung

Bei Änderungen am Repository-Add-on muss dessen Versionsnummer in `addons/repository.bender2403/addon.xml` erhöht werden. Bei Änderungen an den Repository-URLs muss die Repository-Add-on-Version ebenfalls erhöht werden.

**RTL+ und Rakuten TV sowie externe Repository-Installer werden nicht mehr automatisch aus anderen Repositories geladen.**
