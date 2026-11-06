# Kodi-Repository von Bender2403

Dieses öffentliche Repository stellt geprüfte Add-ons für Kodi bereit.

## Repository in Kodi installieren

Repository-ZIP:
`https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/repository.bender2403/repository.bender2403-1.0.1.zip`

Repository-Metadaten:
- `https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/addons.xml`
- `https://raw.githubusercontent.com/Bender2403/repository.bender2403/main/addons.xml.md5`

## Automatische Veröffentlichung und Updates

Die Quellordner liegen unter `addons/<addon-id>/`. Bei jedem Push nach `main` baut GitHub Actions automatisch:
- die zentrale `addons.xml`,
- die Prüfsumme `addons.xml.md5`,
- pro Add-on einen Ordner `<addon-id>/` mit Add-on-Dateien und ZIP-Paket.

Diese generierten Dateien werden direkt in den Hauptbranch committed. Kodi kann dadurch neue Add-on-Versionen über das installierte Repository erkennen.

Bei Änderungen am Repository-Add-on muss dessen Versionsnummer in `addons/repository.bender2403/addon.xml` erhöht werden. Bei Änderungen an den Repository-URLs muss die Repository-Add-on-Version ebenfalls erhöht werden, damit Kodi die Quelle neu einliest.

## Aufbau

- `addons/`: Quellordner der veröffentlichten Kodi-Add-ons
- `scripts/build_repo.py`: Erzeugt ZIP-Dateien, `addons.xml` und Prüfsumme
- `.github/workflows/publish.yml`: Baut und veröffentlicht die Dateien automatisch
- `<addon-id>/`: Automatisch erzeugte Veröffentlichungsordner mit ZIP-Dateien

Neue Add-ons werden nur aufgenommen, wenn sie als Quellordner unter `addons/` liegen.

**Rakuten TV und RTL+ sind ausdrücklich nicht Bestandteil dieses Repositorys.**
