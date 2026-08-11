# tests/cli/test_main_parallel.py

from unittest.mock import MagicMock, patch

import pytest

from conclave.cli.main import build_parser


def test_parser_has_orchestrate_parallel_command():
    parser = build_parser()
    args = parser.parse_args([
        "orchestrate-parallel", "conv-1", "--groups", "a,b", "c",
    ])
    assert args.command == "orchestrate-parallel"
    assert args.conversation_id == "conv-1"
    assert args.groups == ["a,b", "c"]
