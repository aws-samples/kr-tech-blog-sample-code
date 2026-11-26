#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SPIFFE X.509-SVID mTLS 예제 클라이언트 (Python 표준 라이브러리만 사용).

- 자기 SVID(svid.0.pem, svid.0.key)를 클라이언트 인증서로 제시합니다.
- 서버 인증서를 trust bundle(bundle.0.pem)로 검증하고, URI SAN의 SPIFFE ID가 --expect-server와 같은지 확인합니다.
  SVID에는 DNS 이름이 없으므로 호스트 이름 검증 대신 SPIFFE ID를 비교합니다.
- 결과를 한 줄(result=..., http=...)로 출력합니다. 종료 코드: 0 성공, 1 HTTP 오류, 2 TLS/연결 실패, 3 서버 ID 불일치.

예제 코드이며 운영 환경용이 아닙니다.
"""
import argparse
import os
import socket
import ssl
import sys


def spiffe_id_of(cert):
    uris = [v for k, v in cert.get('subjectAltName', ()) if k == 'URI']
    if len(uris) != 1 or not uris[0].startswith('spiffe://'):
        return None
    return uris[0]


def main():
    ap = argparse.ArgumentParser(description='SPIFFE mTLS example client')
    ap.add_argument('--host', required=True)
    ap.add_argument('--port', type=int, default=8443)
    ap.add_argument('--svid-dir', required=True, help='svid.0.pem, svid.0.key, bundle.0.pem이 있는 디렉터리')
    ap.add_argument('--expect-server', required=True, help='서버가 가져야 할 SPIFFE ID')
    ap.add_argument('--path', default='/orders')
    ap.add_argument('--timeout', type=float, default=5)
    a = ap.parse_args()

    j = lambda n: os.path.join(a.svid_dir, n)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False                       # SPIFFE ID로 대신 검증
    ctx.verify_mode = ssl.CERT_REQUIRED
    try:
        ctx.load_verify_locations(j('bundle.0.pem'))
        ctx.load_cert_chain(j('svid.0.pem'), j('svid.0.key'))
    except (OSError, ssl.SSLError) as e:
        print(f'result=FAIL stage=svid_files dir={a.svid_dir} reason={type(e).__name__}: {e}')
        return 2

    try:
        with socket.create_connection((a.host, a.port), timeout=a.timeout) as raw:
            with ctx.wrap_socket(raw) as tls:
                server_id = spiffe_id_of(tls.getpeercert())
                if server_id != a.expect_server:
                    print(f'result=REJECT stage=server_id expected={a.expect_server} got={server_id}')
                    return 3
                req = f'GET {a.path} HTTP/1.1\r\nHost: {a.host}\r\nConnection: close\r\n\r\n'
                tls.sendall(req.encode())
                resp = b''
                while True:
                    chunk = tls.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
    except ssl.SSLError as e:
        print(f'result=FAIL stage=tls reason={e.reason or e}')
        return 2
    except OSError as e:
        print(f'result=FAIL stage=connect reason={type(e).__name__}: {e}')
        return 2

    head, _, body = resp.partition(b'\r\n\r\n')
    status_line = head.split(b'\r\n', 1)[0].decode(errors='replace')
    code = status_line.split(' ')[1] if ' ' in status_line else '000'
    print(f'result={"OK" if code == "200" else "DENIED"} server={server_id} http={code} body={body.decode(errors="replace").strip()}')
    return 0 if code == '200' else 1


if __name__ == '__main__':
    sys.exit(main())
