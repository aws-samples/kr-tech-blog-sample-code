"""Sample application - stable version"""
import http.server
import json
import os
import sys


def load_config():
    """Load configuration from environment variable."""
    config_str = os.environ.get("APP_CONFIG", '{"app_name": "sample-app", "port": 8080}')
    config = json.loads(config_str)
    return config


def main():
    config = load_config()
    port = config["port"]
    app_name = config["app_name"]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(f"Hello from {app_name}!\n".encode())

    print(f"Starting {app_name} on port {port}")
    server = http.server.HTTPServer(("", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
