# Phase 2: Personal Surface

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Die sichtbare Enterprise-/Compliance-Oberfläche wurde aus Conclave Personal
entfernt. Das Produkt verhält sich jetzt als lokales Multi-Agent-Werkzeug für
einzelne Nutzer: Conversations, Agents, Workspace, Usage und Export bleiben; die
früheren Consent-, DPA-, Audit-Report- und Admin-Purge-Schnittstellen sind aus
API, CLI, MCP und UI entfernt.

## Umgesetzt

- REST-API gekürzt:
  - entfernt: `/conversations/<id>/consent`
  - entfernt: `/dpa`
  - entfernt: `/audit`
  - entfernt: `/admin/purge`
  - erhalten: `/conversations/<id>/export`, `/usage`, `/usage/conversations`, `/workspace`
- CLI gekürzt:
  - entfernt: `consent-grant`, `consent-revoke`, `dpa-register`, `dpa-list`, `purge`
  - erhalten: `export`, Usage-, Conversation-, Agent- und Orchestrierungsbefehle
- UI gekürzt:
  - der alte Privacy-Tab wurde zu `Workspace`
  - Consent-/DPA-Sektionen und Modals wurden entfernt
  - Conversation-Export ist jetzt eine neutrale Personal-Funktion
- MCP-Tools gekürzt:
  - Consent- und DPA-Tools entfernt
  - Export bleibt als Backup-/Artefakt-Funktion erhalten
- Codepfade entfernt:
  - `ComplianceService`
  - `TransferPolicy`
  - Consent-/DPA-Domainobjekte
  - SQLite-/Postgres-Repositories für Consent/DPA
  - Provider-Metadaten für Drittland-Policy
- Rollenmodell bereinigt:
  - `compliance_admin` wurde im aktiven RBAC-Modell durch `owner` ersetzt
- API-Dokumentation neu generiert:
  - `static/openapi.json`
  - `docs/referenz/api.md`
- Tests angepasst:
  - neue Negativtests sichern, dass entfernte Enterprise-Routen und CLI-Kommandos nicht mehr verfügbar sind
  - alte Compliance-/Transfer-/Consent-/DPA-Testmodule entfernt

## Verifikation

```powershell
python -m pytest
```

Ergebnis:

```text
688 passed, 1 skipped
```

## Abnahme

- Keine aktive Python-Abhängigkeit auf `compliance_service`, `transfer_policy`,
  `ConsentRecord`, `DpaRecord`, `ConsentNotGranted`, `DpaNotRegistered` oder
  `TransferNotAllowed`.
- Die OpenAPI-Spec enthält nur noch die aktuellen Personal-Routen.
- Die Browser-UI zeigt keine Consent-/DPA-Verwaltung mehr.
- Der lokale Workspace und Conversation-Export bleiben für Personal Workflows
  verfügbar.

## Nächster sinnvoller Schritt

Phase 3 sollte die Runtime konsequent multiplattformfähig machen: Startbefehle,
Pfadlogik, Workspace-Defaults, Service-/Autostart-Skripte und Packaging für
Windows und Linux.
