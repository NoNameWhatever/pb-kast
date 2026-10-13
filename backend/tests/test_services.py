import os
import socket
from urllib.parse import urlparse


def _connect(url):
    u = urlparse(os.environ[url])
    return socket.create_connection((u.hostname, u.port), timeout=5)


def test_postgres_service_is_reachable():
    with _connect("DATABASE_URL") as s:
        s.sendall(b"\x00\x00\x00\x08\x04\xd2\x16\x2f")  # SSLRequest: any Postgres answers S or N
        assert s.recv(1) in (b"S", b"N")


def test_redis_service_is_reachable():
    with _connect("REDIS_URL") as s:
        s.sendall(b"PING\r\n")
        assert s.recv(16).startswith(b"+PONG")
