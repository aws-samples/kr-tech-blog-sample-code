#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SPIFFE X.509-SVID mTLS 예제 서버 (Python 표준 라이브러리만 사용).

- TLS 단계: 클라이언트 인증서를 필수로 요구하고, trust bundle(bundle.0.pem)의 CA 서명과 유효 기간을 검증합니다.
- 애플리케이션 단계: 클라이언트 인증서 URI SAN의 SPIFFE ID를 허용 규칙(--allow 정확 일치, --allow-prefix 접두사)과 비교합니다.
- 판정은 한 줄 로그(decision=ALLOW|REJECT)로 남깁니다.

SVID 디렉터리는 `spire-agent api fetch x509 -write <dir>`이 만든 svid.0.pem, svid.0.key, bundle.0.pem을 사용합니다.
예제 코드이며 운영 환경용이 아닙니다.
"""
import argparse
import json
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def log(**fields):
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(ts + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()), flush=True)


def spiffe_id_of(cert):
    """getpeercert() 결과에서 URI SAN을 꺼냅니다. X.509-SVID는 URI SAN이 정확히 하나여야 합니다."""
    uris = [v for k, v in cert.get('subjectAltName', ()) if k == 'URI']
    if len(uris) != 1 or not uris[0].startswith('spiffe://'):
        return None
    return uris[0]


class SvidContext:
    """SVID 파일로 서버용 SSLContext를 만들고, --reload이면 파일이 바뀔 때 다시 만듭니다."""

    def __init__(self, svid_dir, reload):
        self.paths = [os.path.join(svid_dir, n) for n in ('svid.0.pem', 'svid.0.key', 'bundle.0.pem')]
        self.reload = reload
        self.lock = threading.Lock()
        self.stamp = None
        self.ctx = None
        self.get()

    def _build(self):
        cert, key, bundle = self.paths
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.verify_mode = ssl.CERT_REQUIRED          # 클라이언트 인증서 필수
        ctx.load_cert_chain(cert, key)
        ctx.load_verify_locations(bundle)            # SPIRE CA만 신뢰
        return ctx

    def get(self):
        with self.lock:
            stamp = tuple(os.stat(p).st_mtime_ns for p in self.paths)
            if self.ctx is None or (self.reload and stamp != self.stamp):
                self.ctx = self._build()
                if self.stamp is not None:
                    log(event='svid_reloaded')
                self.stamp = stamp
            return self.ctx


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, svid, allow, allow_prefix):
        super().__init__(addr, Handler)
        self.svid, self.allow, self.allow_prefix = svid, allow, allow_prefix

    def handle_error(self, request, client_address):
        # 핸드셰이크 뒤 클라이언트가 먼저 끊는 경우(서버 ID 불일치 등)는 한 줄로만 남깁니다
        exc = sys.exc_info()[1]
        log(event='connection_closed', peer=client_address[0], reason=type(exc).__name__)

    def get_request(self):
        raw, addr = self.socket.accept()
        raw.settimeout(10)
        try:
            tls = self.svid.get().wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError) as e:
            reason = getattr(e, 'reason', None) or type(e).__name__
            log(decision='REJECT', stage='tls', peer=addr[0], reason=reason)
            raw.close()
            raise
        return tls, addr


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                                          # 판정 로그만 남깁니다

    def do_GET(self):
        peer_id = spiffe_id_of(self.connection.getpeercert())
        srv = self.server
        ok = peer_id is not None and (
            peer_id in srv.allow or any(peer_id.startswith(p) for p in srv.allow_prefix))
        if ok:
            log(decision='ALLOW', stage='authz', peer=self.client_address[0], spiffe_id=peer_id, path=self.path)
            self._send(200, {'result': 'ok', 'caller': peer_id, 'path': self.path})
        else:
            log(decision='REJECT', stage='authz', peer=self.client_address[0], spiffe_id=peer_id, path=self.path)
            self._send(403, {'result': 'forbidden', 'caller': peer_id})

    def _send(self, code, body):
        data = (json.dumps(body) + '\n').encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description='SPIFFE mTLS example server')
    ap.add_argument('--bind', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8443)
    ap.add_argument('--svid-dir', required=True, help='svid.0.pem, svid.0.key, bundle.0.pem이 있는 디렉터리')
    ap.add_argument('--allow', action='append', default=[], help='허용할 SPIFFE ID (정확 일치, 여러 번 지정 가능)')
    ap.add_argument('--allow-prefix', action='append', default=[], help='허용할 SPIFFE ID 접두사 (여러 번 지정 가능)')
    ap.add_argument('--reload', action='store_true', help='SVID 파일이 바뀌면 재시작 없이 다시 읽음')
    a = ap.parse_args()
    if not a.allow and not a.allow_prefix:
        ap.error('--allow 또는 --allow-prefix를 하나 이상 지정하세요')
    for p in a.allow_prefix:
        if not p.endswith('/'):
            ap.error(f'--allow-prefix는 /로 끝나야 합니다: {p}')

    svid = SvidContext(a.svid_dir, a.reload)
    srv = Server((a.bind, a.port), svid, set(a.allow), a.allow_prefix)
    log(event='listening', bind=a.bind, port=a.port, allow=','.join(a.allow) or '-',
        allow_prefix=','.join(a.allow_prefix) or '-')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    sys.exit(main())
