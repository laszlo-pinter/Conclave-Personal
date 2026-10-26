import socket


def set_exclusive_bind(sock: socket.socket) -> None:
    """Binden soll an einem belegten Port scheitern.

    Unter Windows erlaubt SO_REUSEADDR, einen Port zu binden, auf dem bereits ein
    anderer Prozess lauscht - beide "laufen", Verbindungen landen beim alten.
    Dort ist SO_EXCLUSIVEADDRUSE richtig; unter POSIX verhindert SO_REUSEADDR
    das Doppelbinden nicht und erlaubt nur schnelles Neustarten.
    """
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            set_exclusive_bind(sock)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def find_free_port(host: str = "127.0.0.1", preferred: int = 8000) -> int:
    if preferred > 0 and is_port_available(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
