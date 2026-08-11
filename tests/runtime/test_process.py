import socket

from conclave.runtime.process import find_free_port, is_port_available


def test_find_free_port_returns_bindable_port():
    port = find_free_port("127.0.0.1", preferred=0)

    assert isinstance(port, int)
    assert port > 0


def test_is_port_available_detects_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

        assert is_port_available("127.0.0.1", port) is False
