# Kodi-Add-on-Quarantäne

Dieser Ordner enthält Add-on-Quellordner, die der automatische Validator wegen erkannter Fehler aus `addons/` verschoben hat.

## Struktur

Jedes Add-on liegt in einem eigenen Unterordner. Der Ordnername entspricht der Add-on-ID bzw. dem ursprünglichen Quellordnernamen.

```text
_quarantine/
├── README.md
├── plugin.video.beispiel/
└── script.beispiel/
```

## Verhalten

- Der Validator verschiebt fehlerhafte Add-ons bei einem Push auf `main` hierher.
- Vorhandene Quarantäneordner werden niemals überschrieben. Bei einem Namenskonflikt bleibt das Add-on in `addons/` und die Prüfung meldet einen Fehler.
- Pull-Request-Prüfungen verschieben keine Dateien.
- Der Restore-Workflow prüft ein Add-on erneut und verschiebt es nur bei erfolgreicher Validierung zurück nach `addons/`.
- Ein vorhandener Quellordner wird beim Wiederherstellen niemals überschrieben.

Die Quarantäne ist kein Veröffentlichungsordner. Inhalte hier werden nicht in das Kodi-Repository aufgenommen.
