# Kodi-Repository von Bender2403

Dieses öffentliche Repository stellt Add-ons für Kodi bereit.

## Repository in Kodi installieren

Nach Aktivierung von GitHub Pages lautet die Repository-Adresse:

`https://bender2403.github.io/repository.bender2403/`

## Automatische Updates – einschließlich dieses Repository-Add-ons

Das Add-on `repository.bender2403` wird selbst in `addons.xml` aufgenommen und als ZIP unter `zips/repository.bender2403/` veröffentlicht. Dadurch kann Kodi auch Aktualisierungen des Repository-Add-ons über die bereits installierte Repository-Quelle finden und installieren.

Wenn das Repository-Add-on geändert wird:

1. Die Versionsnummer in `addons/repository.bender2403/addon.xml` erhöhen (zum Beispiel `1.0.0` auf `1.0.1`).
2. Änderungen nach `main` übernehmen.
3. GitHub Actions baut automatisch die ZIP-Datei, `addons.xml` und die Prüfsumme und veröffentlicht sie über GitHub Pages.
4. Kodi kann die neue Version anschließend über die normale Add-on-Aktualisierung beziehen.

Die Versionsnummer muss bei jeder Veröffentlichung erhöht werden. Eine bestehende Version wird nicht überschrieben.

## Aufbau

- `addons/`: Quellordner der veröffentlichten Kodi-Add-ons
- `scripts/build_repo.py`: Erzeugt ZIP-Dateien, `addons.xml` und Prüfsumme
- `.github/workflows/publish.yml`: Baut und veröffentlicht das Repository automatisch

Neue Add-ons werden erst nach Prüfung und ausdrücklicher Aufnahme in `addons/` veröffentlicht.

**Hinweis:** Rakuten TV und RTL+ sind derzeit nicht Bestandteil dieses Repositorys.

## Einmalige GitHub-Pages-Einstellung

GitHub Pages muss für dieses Repository einmalig unter **Settings → Pages → Build and deployment → Source: GitHub Actions** aktiviert werden. Danach übernimmt der Workflow die Veröffentlichungen automatisch.
