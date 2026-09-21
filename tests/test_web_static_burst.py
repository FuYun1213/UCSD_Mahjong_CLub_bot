"""The real static handler survives concurrent browser asset connections."""
from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import threading

import web_server


def test_static_assets_survive_bursts_with_existing_keepalive_connections():
    class QuietHandler(web_server.Handler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass

    server = web_server.WebHTTPServer(("127.0.0.1", 0), QuietHandler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    held = []
    expected = (Path(web_server.WEB_DIR) / "account-avatar.js").read_bytes()

    def read(connection):
        connection.request("GET", "/account-avatar.js?v=registration-v10")
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200
        assert response.getheader("Content-Type") in {"text/javascript", "application/javascript"}
        assert int(response.getheader("Content-Length")) == len(expected)
        assert body == expected

    try:
        # Browser connections from already-open pages remain alive while a new
        # navigation starts many independent asset requests.
        for _ in range(8):
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            read(connection)
            held.append(connection)
        for _ in range(2):
            ready = threading.Barrier(48)
            def fetch(_index):
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    ready.wait(timeout=15)
                    read(connection)
                    read(connection)  # The same socket can serve the next asset.
                finally:
                    connection.close()
            with ThreadPoolExecutor(48) as clients:
                list(clients.map(fetch, range(48)))
        for connection in held:
            read(connection)
    finally:
        for connection in held:
            connection.close()
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)
