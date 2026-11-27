# Changelog

Alle wichtigen Änderungen am Bender2403 Kodi-Add-on-Repository werden hier dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Versionsnummern des Repository-Add-ons entsprechen den Versionen in
`addons/repository.bender2403/addon.xml`.

## [Unreleased]

### Geändert

- Repository-Icon auf PNG mit 256 × 256 Pixeln umgestellt; das vorhandene Motiv wurde quadratisch zugeschnitten und für den Kodi-Checker optimiert.

- Kodi-Add-on-Validator prüft generische Extension Points und behandelt optionale Einstellungs- und Sprachdateien nicht mehr als zwingende Voraussetzungen.
- Python-Dateien werden ohne Erzeugung von __pycache__- oder .pyc-Dateien syntaktisch geprüft.
- Fehlerhafte Add-on-Quellordner können beim Push sicher in Quarantäne verschoben werden.
- Wiederherstellung validiert Add-ons erneut und überschreibt keine vorhandenen Quellordner.
- Validierungs- und Wiederherstellungsworkflows sichern erfolgreiche Dateioperationen auch dann, wenn andere Add-ons fehlerhaft bleiben.
- Regressionstests für optionale Dateien, Python-Syntax, unsichere Library-Pfade, Quarantäne und sichere Wiederherstellung ergänzt.
- Quarantäneordner `_quarantine/` mit README und dokumentiertem Restore-Ablauf fest verankert.
- Externe Add-on-ZIPs werden vor dem Entpacken auf Pfadmanipulation, Symlinks, doppelte Einträge, Dateianzahl, Einzel-/Gesamtgröße, Kompressionsverhältnis und Add-on-Metadaten geprüft.
- ZIP-Inhalte werden zunächst in einem Staging-Ordner entpackt und das Veröffentlichungsverzeichnis erst nach erfolgreicher Prüfung atomar ersetzt.
- Komprimierte ZIP-Dateien sind zusätzlich auf 50 MiB begrenzt; lokale Add-on-Ausgaben werden ebenfalls staged und atomar ersetzt, Symlinks im Quellordner abgelehnt.
- Kollisionen zwischen Add-on-Quellordnern und `EXTERNAL_ZIPS` werden erkannt; ZIP-Sicherheits-Regressionstests laufen vor Veröffentlichung.
- Offiziellen Kodi-Addon-Checker für Nexus, Omega und Piers ergänzt; jede Zielversion erhält einen eigenen Bericht.
- Kodi-Kompatibilitätsprüfung läuft sowohl bei Add-on-Validierungen als auch als Pflichtprüfung vor dem Repository-Build und der Veröffentlichung.

## [1.0.1] - 2026-11-06

### Geändert

- Repository-Veröffentlichung auf die Kodi-übliche Verzeichnisstruktur im Hauptbranch umgestellt.
- `addons.xml`, `addons.xml.md5` und versionierte ZIP-Dateien werden direkt im Repository bereitgestellt.
- Repository-Add-on verwendet HTTPS-Raw-GitHub-Adressen und Version 1.0.1.
- GitHub Actions veröffentlicht generierte Dateien automatisch im Hauptbranch.

## [1.0.0] - 2026-11-06

### Hinzugefügt

- Erstveröffentlichung des Kodi-Repository-Add-ons `repository.bender2403`.
- Automatischer Aufbau der `addons.xml` und der MD5-Prüfsumme.
- Automatische Erstellung der Add-on-ZIP-Dateien.
- Veröffentlichung über GitHub Pages mittels GitHub Actions.
- Unterstützung für die Aktualisierung des Repository-Add-ons über das eigene Kodi-Repository.
- Repository-Symbol (`icon.jpg`).
