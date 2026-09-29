"""Sample application - refactored config loading"""
import http.server
import json
import os
import sys


def load_config():
    """Load configuration from environment variable.

    Refactored: now requires APP_CONFIG to be set explicitly.
    Removed default fallback for stricter configuration management.
    """
    config_str = os.environ.get("APP_CONFIG")
    if config_str is None:
        print("FATAL: APP_CONFIG environment variable is required", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_str)

    # Validate required fields
    required_fields = ["app_name", "port", "database_url"]
    for field in required_fields:
        if field not in config:
            print(f"FATAL: missing required config field: {field}", file=sys.stderr)
            sys.exit(1)

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
