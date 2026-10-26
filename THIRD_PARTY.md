# Drittanbieter-Komponenten

Komponenten, die als Dateien mit Conclave ausgeliefert werden. Zur Laufzeit wird
nichts von fremden Servern geladen. Alle Dateien liegen unter
`src/conclave/assets/static/vendor/`, die Lizenztexte unter `vendor/licenses/`.

| Komponente | Version | Dateien | Lizenz | Quelle (npm) |
|---|---|---|---|---|
| DOMPurify | 3.4.17 | `purify.min.js` | Apache-2.0 oder MPL-2.0 | `dompurify@3.4.17`, `dist/purify.min.js` |
| marked | 15.0.7 | `marked.min.js` | MIT | `marked@15.0.7`, `marked.min.js` |
| highlight.js | 11.11.1 | `highlight/highlight.min.js`, `highlight/github-dark.min.css` | BSD-3-Clause | `@highlightjs/cdn-assets@11.11.1` |
| Swagger UI | 5.33.2 | `swagger-ui/swagger-ui-bundle.js`, `swagger-ui/swagger-ui.css` | Apache-2.0 | `swagger-ui-dist@5.33.2` |
| Syne | Fontsource 5.3.0 | `fonts/syne-latin-*.woff2` | SIL OFL 1.1 | `@fontsource/syne@5.3.0` |
| Syne Mono | Fontsource 5.3.0 | `fonts/syne-mono-latin-400-normal.woff2` | SIL OFL 1.1 | `@fontsource/syne-mono@5.3.0` |
| DM Sans | Fontsource 5.3.0 | `fonts/dm-sans-latin-*.woff2` | SIL OFL 1.1 | `@fontsource/dm-sans@5.3.0` |

`fonts/fonts.css` ist eigener Code (`@font-face`-Deklarationen).

## npm-Integrität der Pakete

| Paket | Integrität |
|---|---|
| `dompurify@3.4.17` | `sha512-B/pSlYVHQ58kqISD/yDjuJ1yfzI34m1gF4lAod2bwSRhiN4K5Cl3H8Af7hqB2PmTL911tdEudnnXn5FnhRoz0w==` |
| `marked@15.0.7` | `sha512-dgLIeKGLx5FwziAnsk4ONoGwHwGPJzselimvlVskE9XLN4Orv9u2VA3GWw/lYUqjfA0rUT/6fqKwfZJapP9BEg==` |
| `@highlightjs/cdn-assets@11.11.1` | `sha512-VEPdHzwelZ12hEX18BHduqxMZGolcUsrbeokHYxOUIm8X2+M7nx5QPtPeQgRxR9XjhdLv4/7DD5BWOlSrJ3k7Q==` |
| `swagger-ui-dist@5.33.2` | `sha512-MyrWX06zkJRYPnIau8Qj8F6KfzS+Qj8D9AR36vCWkkC9ts1r1DYF84apgCvZBzO2Wzm7G7loCd5VS+4JLWoyLQ==` |
| `@fontsource/syne@5.3.0` | `sha512-kRWNVsrdYw+08I4EM1SYPe2JovdTzUI0kMVALVRsKmjRdkrVoun1qddSlDAglz5J9LbgUpJSkWmw6BYnmKdGuw==` |
| `@fontsource/syne-mono@5.3.0` | `sha512-2kxuhmZ4+93IFSeS8jqTQ3QYG6z0gDWKAlJ4pU1/gm/ZzYCLyHwviYYu45+1fqsILDDrfvHEKERyWItkY89tag==` |
| `@fontsource/dm-sans@5.3.0` | `sha512-lYJtMXXO28q1z+yz+z8XKd0s4hXaa9QdkETzkyD760sidCv5heI86weYA0sx0Nc4pAMAQTUuyf4gO44cYKKS9g==` |

## Prüfsummen (SHA-256)

`tests/packaging/test_vendor_assets.py` prüft diese Tabelle gegen die Dateien.

| Datei | SHA-256 |
|---|---|
| `fonts/dm-sans-latin-300-italic.woff2` | `bdd25fa33d0dfdeeb007471c64611df30cfe1879270db8c47e8159f24047e64b` |
| `fonts/dm-sans-latin-300-normal.woff2` | `80f13c410ec41f210a5553e7f420f8a51f459180019274df0b3faea314916f90` |
| `fonts/dm-sans-latin-400-normal.woff2` | `4ab51eb2cd7305d177187908d6397474d4520663f6c6e572feb0a64f4fa80006` |
| `fonts/dm-sans-latin-500-normal.woff2` | `19bf1984956517c35c2bd35b6cdedac12a21d6fcd3596c614ecdfb88b648909d` |
| `fonts/fonts.css` | `83a1f42a5b5a802a95524438c93220b361543a91f8ebe8e72dee2cbbefdb9768` |
| `fonts/syne-latin-400-normal.woff2` | `98ffc84a339a19a2b3af38d8ead818823eed865bdc419693c77c9929494acca2` |
| `fonts/syne-latin-600-normal.woff2` | `f1dc13cad7ce032771fc930cca6f5693074faf907cd67e051b74f508b7721265` |
| `fonts/syne-latin-700-normal.woff2` | `0aad69416fc0ccf6f340647c46e759d5c6e4628d92576b279ec5ada0afbd9d35` |
| `fonts/syne-latin-800-normal.woff2` | `1a340e84b78c7e1e7ed24306d682fdcd6dc8cc6cb52b158fbaf22c03f7f001c3` |
| `fonts/syne-mono-latin-400-normal.woff2` | `30ac9fd8d8768c6dc75dae3ee4c39d864cb72f9ba8d9f2e25419179510b25f7b` |
| `highlight/github-dark.min.css` | `9f208d022102b1d0c7aebfecd8e42ca7997d5de636649d2b31ea63093d809019` |
| `highlight/highlight.min.js` | `c4a399dd6f488bc97a3546e3476747b3e714c99c57b9473154c6fb8d259b9381` |
| `licenses/dm-sans-OFL.txt` | `6fbd040a29c2037a765dfb9f2561e9965b5c95c6dcb5dce516089d63d5f17af7` |
| `licenses/dompurify-LICENSE.txt` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `licenses/highlightjs-LICENSE.txt` | `6c081431591d9df696c82dc598fe1423765b8a299b200ed00b281afd0f64c490` |
| `licenses/marked-LICENSE.txt` | `8e3a3f82f59a60958f56ca08f445647c32a4733dc7ca6c2c46f6eb898471ab9c` |
| `licenses/swagger-ui-LICENSE.txt` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `licenses/swagger-ui-NOTICE.txt` | `0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2` |
| `licenses/syne-mono-OFL.txt` | `ea775d83f01ecd45fc622fa5db568fad99c9338192594c3719a52b78bab91e44` |
| `licenses/syne-OFL.txt` | `ea775d83f01ecd45fc622fa5db568fad99c9338192594c3719a52b78bab91e44` |
| `marked.min.js` | `934e3e36e9e2da0afb1a6e75075bb0f09af05293a844e84a7477ef40911c349a` |
| `purify.min.js` | `cd37898f9782adf54820c413191b5691803f0f137c799d6edcfd38523b4c2c31` |
| `swagger-ui/swagger-ui-bundle.js` | `6b3bfcaff3fc82c0e6992ca4b370c4f22970dec35fff60d229302b3ee7688715` |
| `swagger-ui/swagger-ui.css` | `1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321` |

## Aktualisieren

1. `npm pack <paket>@<version>` in einem leeren Verzeichnis ausführen (npm prüft
   die Integrität gegen die Registry). Nur Versionen verwenden, die mindestens
   zwei Wochen alt sind.
2. Die oben genannten Dateien und den Lizenztext nach `vendor/` kopieren.
3. Version, Integrität und Prüfsummen in dieser Datei aktualisieren.
4. `python -m pytest tests/ui tests/packaging tests/api/test_security_headers.py` ausführen.
