# Drittanbieter-Komponenten

Komponenten, die als Dateien mit Conclave ausgeliefert werden (keine Laufzeit-Downloads).

| Komponente | Version | Datei | Lizenz | Quelle |
|---|---|---|---|---|
| DOMPurify | 3.4.17 | `src/conclave/assets/static/vendor/purify.min.js` | Apache-2.0 oder MPL-2.0 | npm `dompurify@3.4.17`, `dist/purify.min.js` |

## Prüfsummen

| Datei | SHA-256 |
|---|---|
| `purify.min.js` | `cd37898f9782adf54820c413191b5691803f0f137c799d6edcfd38523b4c2c31` |

npm-Integrität des Pakets `dompurify@3.4.17`:
`sha512-B/pSlYVHQ58kqISD/yDjuJ1yfzI34m1gF4lAod2bwSRhiN4K5Cl3H8Af7hqB2PmTL911tdEudnnXn5FnhRoz0w==`

## Aktualisieren

1. `npm pack dompurify@<version>` in einem leeren Verzeichnis ausführen (npm prüft die Integrität gegen die Registry).
2. `package/dist/purify.min.js` nach `src/conclave/assets/static/vendor/` kopieren.
3. Version und Prüfsummen in dieser Datei aktualisieren.
4. `python -m pytest tests/ui` ausführen.
