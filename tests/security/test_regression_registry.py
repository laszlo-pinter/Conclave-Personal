"""R15 (conclave#50): Jeder Befund der Sicherheitsanalyse (SA-01 bis SA-21) hat Regressionstests.

Die Analyse selbst ist nicht oeffentlich; hier stehen nur die Kennungen, das Ticket
der Behebung und die Testdateien. Faellt eine Datei weg oder verliert sie ihre
Tests, scheitert dieser Test.
"""

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]

# Befund -> (Ticket der Behebung, Testdateien)
REGRESSION_TESTS = {
    "SA-01": ("R1", ["infrastructure/test_migrations.py", "persistence/test_postgres_migrations.py",
                     "security/test_crash_safety.py"]),
    "SA-02": ("R3", ["runtime/test_provider_key_binding.py", "ui/test_agent_url_hint_browser.py"]),
    "SA-03": ("R2", ["mcp/test_mcp_server.py", "api/test_access_security.py"]),
    "SA-04": ("R4", ["api/test_access_security.py", "ui/test_path_segments_browser.py"]),
    "SA-05": ("R5", ["ui/test_token_safety_browser.py", "cli/test_web_token.py"]),
    "SA-06": ("R6", ["application/test_workspace_budget.py", "api/test_request_limits.py"]),
    "SA-07": ("R7", ["runtime/test_backup_restore_safety.py", "security/test_crash_safety.py"]),
    "SA-08": ("R12", ["infrastructure/universal/test_egress.py"]),
    "SA-09": ("R12", ["api/test_error_redaction.py", "infrastructure/test_universal/test_profiles.py"]),
    "SA-10": ("R6", ["application/test_workspace_directives.py", "api/test_workspace_rules.py"]),
    "SA-11": ("R8", ["api/test_workspace_rules.py"]),
    "SA-12": ("R8", ["api/test_workspace_rules.py", "security/test_crash_safety.py"]),
    "SA-13": ("R9", ["application/test_board_history.py", "api/test_board_security.py",
                     "application/test_board_service.py"]),
    "SA-14": ("R10", ["application/test_consultation_limits.py", "persistence/test_postgres_consultations.py",
                      "application/test_consultation_service.py"]),
    "SA-15": ("R13", ["runtime/test_file_security.py", "runtime/test_secret_key_rotation.py",
                      "persistence/test_postgres_key_rotation.py"]),
    "SA-16": ("R7", ["runtime/test_backup_restore_safety.py", "api/test_workspace_rules.py"]),
    "SA-17": ("R5", ["ui/test_token_safety_browser.py"]),
    "SA-18": ("R5", ["ui/test_token_safety_browser.py", "cli/test_web_token.py"]),
    "SA-19": ("R15", ["security/test_route_matrix.py", "security/test_create_app_auth.py",
                      "ui/test_html_sinks.py", "packaging/test_vendor_npm.py"]),
    "SA-20": ("R11", ["api/test_agent_limits.py", "persistence/test_postgres_runs.py"]),
    "SA-21": ("R14", ["release/test_release_chain.py", "ci/test_github_actions.py"]),
}


def _test_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]


def test_every_finding_is_listed():
    assert sorted(REGRESSION_TESTS) == [f"SA-{n:02d}" for n in range(1, 22)]


@pytest.mark.parametrize("finding", sorted(REGRESSION_TESTS))
def test_every_finding_has_regression_tests(finding):
    _, files = REGRESSION_TESTS[finding]
    assert files, finding
    for rel in files:
        path = TESTS / rel
        assert path.is_file(), f"{finding}: {rel} fehlt"
        assert _test_functions(path), f"{finding}: {rel} enthaelt keine Tests"
