"""Umgezogen nach ``conclave_reviewer.worktrees`` (TR1); der alte Name ist ein Alias auf dasselbe Modul."""

import sys

from conclave_reviewer.worktrees import __name__ as _target  # noqa: F401  (laedt das Modul)

sys.modules[__name__] = sys.modules[_target]
