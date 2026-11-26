# Strengthening Amazon EC2 Workload Authentication with SPIRE: Sample Code

[한국어](README.ko.md)

This repository contains the sample code used in Step 4 (Scenario 3, SVID-based mTLS communication control) of the AWS Korea Tech Blog post **"Amazon EC2 워크로드 인증을 SPIRE로 강화하기"** (Strengthening Amazon EC2 workload authentication with SPIRE). It shows two workloads authenticating each other over mTLS with X.509-SVIDs issued by SPIRE, and a server allowing or denying callers based on their SPIFFE ID.

> This is sample code, for non-production usage. You should work with your security and legal teams to meet your organizational security, regulatory and compliance requirements before deployment.

## Contents

| File | Runs on (blog example) | Role |
|---|---|---|
| `data_server.py` | Workload A, user `orders` | mTLS sample server. Requires a client certificate and compares the caller's SPIFFE ID with allow rules. |
| `data_client.py` | Workload B, users `portal` and `batch` | Sample caller. Presents its own SVID, verifies the server's SPIFFE ID, then sends a request. |

Both files use only the Python 3 standard library (`ssl`, `socket`, `http.server`, and so on). No additional packages are required.

```
Workload B (portal / batch)                         Workload A (orders)
data_client.py  --- mTLS (TCP 8443) --------------> data_server.py
  - presents its own SVID                             - requires a client certificate
  - verifies the server certificate with the          - verifies the certificate with the trust bundle
    trust bundle                                       - compares the caller SPIFFE ID with
  - checks server SPIFFE ID == --expect-server           --allow / --allow-prefix
```

## Prerequisites

- A SPIRE Agent runs on each workload node, and a workload entry is registered for the user (uid) that runs each program. Follow Steps 1 to 3 of the blog post.
- The SVID directory contains the three files written by `spire-agent api fetch x509 -write <dir>`.

| File | Content |
|---|---|
| `svid.0.pem` | Own X.509-SVID (certificate) |
| `svid.0.key` | SVID private key |
| `bundle.0.pem` | Trust bundle (SPIRE CA certificates) |

## How it works

### data_server.py

1. **TLS stage:** Trusts only the CAs in `bundle.0.pem` and requires a client certificate (`CERT_REQUIRED`, TLS 1.2 or later). The handshake fails if the certificate is missing, signed by another CA, or expired.
2. **Authorization stage:** Extracts the SPIFFE ID from the URI SAN of the client certificate. There must be exactly one URI SAN, and it must start with `spiffe://`. The ID is then compared with the allow rules.
   - `--allow`: allows only an exact SPIFFE ID. Can be specified multiple times.
   - `--allow-prefix`: allows every SPIFFE ID with the given prefix. The value must end with `/`. For example, `spiffe://lab.example.org/frontend/` allows every service under `/frontend/`.
3. **Response:** Returns HTTP 200 with the caller ID when allowed, and HTTP 403 when denied, as JSON.
4. **SVID rotation:** With `--reload`, the server checks the modification time of the three files on each request and rebuilds the TLS context when they change, so it uses rotated SVIDs without a restart.
5. **Logging:** Writes one line per decision to standard output.

```
2026-11-23T04:17:05Z decision=ALLOW stage=authz peer=<caller IP> spiffe_id=spiffe://lab.example.org/frontend/portal path=/orders
2026-11-23T04:17:05Z decision=REJECT stage=tls peer=<caller IP> reason=PEER_DID_NOT_RETURN_A_CERTIFICATE
2026-11-23T04:17:06Z decision=REJECT stage=tls peer=<caller IP> reason=CERTIFICATE_VERIFY_FAILED
```

| Option | Default | Description |
|---|---|---|
| `--bind` | `127.0.0.1` | Listen address. To accept connections from other instances, use `0.0.0.0` and restrict the source with security groups. |
| `--port` | `8443` | Listen port |
| `--svid-dir` | (required) | SVID file directory |
| `--allow` | - | SPIFFE ID to allow (exact match) |
| `--allow-prefix` | - | SPIFFE ID prefix to allow (ends with `/`) |
| `--reload` | off | Reload SVID files when they change |

At least one of `--allow` or `--allow-prefix` is required.

### data_client.py

1. Presents its own SVID (`svid.0.pem`, `svid.0.key`) as the client certificate and verifies the server certificate with `bundle.0.pem`.
2. SVIDs carry no DNS name, so instead of hostname verification the client checks that the SPIFFE ID in the server certificate equals `--expect-server`. If it differs, the client stops without sending a request.
3. Sends `GET <path>` and prints the result on one line.

```
result=OK server=spiffe://lab.example.org/backend/orders http=200 body={"result": "ok", ...}
result=DENIED server=spiffe://lab.example.org/backend/orders http=403 body={"result": "forbidden", ...}
result=FAIL stage=tls reason=TLSV1_ALERT_UNKNOWN_CA
```

| Option | Default | Description |
|---|---|---|
| `--host` | (required) | Server address |
| `--port` | `8443` | Server port |
| `--svid-dir` | (required) | Own SVID file directory |
| `--expect-server` | (required) | SPIFFE ID the server must have |
| `--path` | `/orders` | Request path |
| `--timeout` | `5` | Connection timeout (seconds) |

| Exit code | Meaning |
|---|---|
| 0 | HTTP 200 |
| 1 | HTTP error (for example, 403) |
| 2 | SVID file, TLS, or connection failure |
| 3 | Server SPIFFE ID mismatch |

## Usage example

```bash
# [Workload A] Fetch the server SVID (user orders)
sudo install -d -o orders /opt/lab/svid-orders
sudo -u orders spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-orders >/dev/null

# [Workload A] Run the server: allow only portal (exact match)
sudo -u orders python3 /opt/lab/data_server.py --bind 0.0.0.0 --port 8443 --svid-dir /opt/lab/svid-orders \
  --reload --allow spiffe://lab.example.org/frontend/portal

# [Workload A, another window] SVIDs are short-lived, so fetch again every minute (picked up by --reload)
while true; do
  sudo -u orders spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-orders >/dev/null
  sleep 60
done

# [Workload B] Call: fetch the SVID right before calling
sudo install -d -o portal /opt/lab/svid-portal
sudo -u portal spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-portal >/dev/null
sudo -u portal python3 /opt/lab/data_client.py --host <Workload A private IP> --port 8443 \
  --svid-dir /opt/lab/svid-portal --expect-server spiffe://lab.example.org/backend/orders
```

To switch to the prefix rule, restart the server with `--allow-prefix spiffe://lab.example.org/frontend/` instead of `--allow`.

## Security considerations

- `--bind 0.0.0.0` lets other instances connect. Restrict the source of TCP 8443 to the caller security group. Connections without a client certificate are rejected at the TLS stage.
- Keep the SVID private key (`svid.0.key`) in a directory that only the running user can read. The example creates per-user directories with `install -d -o <user>`.
- The server trusts only the CAs in the SPIRE trust bundle. A certificate signed by another CA is rejected at the TLS stage, even if it carries the same SPIFFE ID.
- This sample fetches SVIDs as files and reloads them periodically. In production, use a SPIFFE library that subscribes to the Workload API (for example, [go-spiffe](https://github.com/spiffe/go-spiffe)), [spiffe-helper](https://github.com/spiffe/spiffe-helper), or Envoy SDS integration.
- The sample server implements only simple HTTP handling. It does not include production features such as request size limits, rate limiting, or audit log storage.

## License

This sample code is made available under the MIT-0 license. See the [LICENSE](LICENSE) file.
