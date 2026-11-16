"""Umgezogen nach ``conclave_board.domain.principal`` (Paketschnitt T1).

Der alte Name bleibt ein Alias auf dasselbe Modul: Imports, ``monkeypatch`` und
``isinstance`` verhalten sich wie vorher.
"""

import sys

from conclave_board.domain.principal import __name__ as _target  # noqa: F401  (laedt das Modul)

sys.modules[__name__] = sys.modules[_target]
