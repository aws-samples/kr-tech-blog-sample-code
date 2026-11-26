# Amazon EC2 워크로드 인증을 SPIRE로 강화하기: 예제 코드

[English](README.md)

AWS Korea Tech Blog 글 **"Amazon EC2 워크로드 인증을 SPIRE로 강화하기"**의 단계 4(시나리오 3, SVID 기반 mTLS 통신 통제)에서 사용하는 예제 코드입니다. SPIRE가 발급한 X.509-SVID로 두 워크로드가 mTLS로 서로를 인증하고, 서버가 호출자의 SPIFFE ID로 접근을 허용하거나 거부하는 과정을 보여 줍니다.

> This is sample code, for non-production usage. You should work with your security and legal teams to meet your organizational security, regulatory and compliance requirements before deployment.

## 구성

| 파일 | 실행 위치(블로그 예제) | 역할 |
|---|---|---|
| `data_server.py` | Workload A, 사용자 `orders` | mTLS 예제 서버. 클라이언트 인증서를 필수로 요구하고, 호출자의 SPIFFE ID를 허용 규칙과 비교합니다. |
| `data_client.py` | Workload B, 사용자 `portal`·`batch` | 예제 호출자. 자기 SVID를 제시해 서버에 접속하고, 서버의 SPIFFE ID를 확인한 뒤 요청합니다. |

두 파일은 Python 3 표준 라이브러리(`ssl`, `socket`, `http.server` 등)만 사용합니다. 별도 패키지 설치가 필요하지 않습니다.

```
Workload B (portal / batch)                         Workload A (orders)
data_client.py  --- mTLS (TCP 8443) --------------> data_server.py
  - 자기 SVID 제시                                     - 클라이언트 인증서 필수
  - 서버 인증서를 trust bundle로 검증                  - 인증서를 trust bundle로 검증
  - 서버 SPIFFE ID == --expect-server 확인             - 호출자 SPIFFE ID를 --allow / --allow-prefix와 비교
```

## 사전 조건

- 각 워크로드 노드에 SPIRE Agent가 동작하고, 실행 사용자(uid)에 맞는 워크로드 entry가 등록되어 있어야 합니다. 절차는 블로그 본문 단계 1~3을 따릅니다.
- SVID 디렉터리는 `spire-agent api fetch x509 -write <dir>`이 만든 아래 세 파일을 담고 있어야 합니다.

| 파일 | 내용 |
|---|---|
| `svid.0.pem` | 자기 X.509-SVID(인증서) |
| `svid.0.key` | SVID 개인 키 |
| `bundle.0.pem` | trust bundle(SPIRE CA 인증서) |

## 동작 방식

### data_server.py

1. **TLS 단계:** `bundle.0.pem`의 CA만 신뢰하고 클라이언트 인증서를 필수로 요구합니다(`CERT_REQUIRED`, TLS 1.2 이상). 인증서가 없거나, 다른 CA가 서명했거나, 만료되었으면 핸드셰이크에서 연결을 끊습니다.
2. **인가 단계:** 클라이언트 인증서의 URI SAN에서 SPIFFE ID를 꺼냅니다. URI SAN이 정확히 하나이고 `spiffe://`로 시작해야 합니다. 이 ID를 허용 규칙과 비교합니다.
   - `--allow`: 정확히 같은 SPIFFE ID만 허용합니다. 여러 번 지정할 수 있습니다.
   - `--allow-prefix`: 접두사가 같은 SPIFFE ID를 모두 허용합니다. 값은 `/`로 끝나야 합니다. 예를 들어 `spiffe://lab.example.org/frontend/`는 `/frontend/` 아래 서비스를 모두 허용합니다.
3. **응답:** 허용되면 HTTP 200과 호출자 ID를, 거부되면 HTTP 403을 JSON으로 돌려줍니다.
4. **SVID 갱신 반영:** `--reload`를 지정하면 요청마다 세 파일의 수정 시각을 확인하고, 바뀌었으면 TLS 설정을 다시 만듭니다. 서버를 재시작하지 않아도 갱신된 SVID를 씁니다.
5. **로그:** 판정마다 한 줄을 표준 출력에 남깁니다.

```
2026-11-23T04:17:05Z decision=ALLOW stage=authz peer=<호출자 IP> spiffe_id=spiffe://lab.example.org/frontend/portal path=/orders
2026-11-23T04:17:05Z decision=REJECT stage=tls peer=<호출자 IP> reason=PEER_DID_NOT_RETURN_A_CERTIFICATE
2026-11-23T04:17:06Z decision=REJECT stage=tls peer=<호출자 IP> reason=CERTIFICATE_VERIFY_FAILED
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--bind` | `127.0.0.1` | 수신 주소. 다른 인스턴스에서 접속하려면 `0.0.0.0`을 지정하고 보안 그룹으로 소스를 제한합니다. |
| `--port` | `8443` | 수신 포트 |
| `--svid-dir` | (필수) | SVID 파일 디렉터리 |
| `--allow` | - | 허용할 SPIFFE ID(정확 일치) |
| `--allow-prefix` | - | 허용할 SPIFFE ID 접두사(`/`로 끝남) |
| `--reload` | 끔 | SVID 파일이 바뀌면 다시 읽음 |

`--allow`와 `--allow-prefix` 중 하나 이상은 반드시 지정해야 합니다.

### data_client.py

1. 자기 SVID(`svid.0.pem`, `svid.0.key`)를 클라이언트 인증서로 제시하고, 서버 인증서를 `bundle.0.pem`으로 검증합니다.
2. SVID에는 DNS 이름이 없으므로 호스트 이름 검증 대신 서버 인증서의 SPIFFE ID가 `--expect-server`와 같은지 확인합니다. 다르면 요청을 보내지 않고 끝냅니다.
3. `GET <path>`를 보내고 결과를 한 줄로 출력합니다.

```
result=OK server=spiffe://lab.example.org/backend/orders http=200 body={"result": "ok", ...}
result=DENIED server=spiffe://lab.example.org/backend/orders http=403 body={"result": "forbidden", ...}
result=FAIL stage=tls reason=TLSV1_ALERT_UNKNOWN_CA
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--host` | (필수) | 서버 주소 |
| `--port` | `8443` | 서버 포트 |
| `--svid-dir` | (필수) | 자기 SVID 파일 디렉터리 |
| `--expect-server` | (필수) | 서버가 가져야 할 SPIFFE ID |
| `--path` | `/orders` | 요청 경로 |
| `--timeout` | `5` | 연결 제한 시간(초) |

| 종료 코드 | 의미 |
|---|---|
| 0 | HTTP 200 |
| 1 | HTTP 오류(예: 403) |
| 2 | SVID 파일, TLS, 연결 실패 |
| 3 | 서버 SPIFFE ID 불일치 |

## 실행 예

```bash
# [Workload A] 서버 SVID 받기 (orders 사용자)
sudo install -d -m 0700 -o orders /opt/lab/svid-orders
sudo -u orders spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-orders >/dev/null

# [Workload A] 서버 실행: portal만 허용(정확 일치)
sudo -u orders python3 /opt/lab/data_server.py --bind 0.0.0.0 --port 8443 --svid-dir /opt/lab/svid-orders \
  --reload --allow spiffe://lab.example.org/frontend/portal

# [Workload A, 다른 창] SVID 수명이 짧으므로 1분마다 다시 받기 (--reload가 반영)
while true; do
  sudo -u orders spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-orders >/dev/null
  sleep 60
done

# [Workload B] 호출: 호출 직전에 SVID 받기
sudo install -d -m 0700 -o portal /opt/lab/svid-portal
sudo -u portal spire-agent api fetch x509 -socketPath /tmp/spire-agent/public/api.sock -write /opt/lab/svid-portal >/dev/null
sudo -u portal python3 /opt/lab/data_client.py --host <Workload A 사설 IP> --port 8443 \
  --svid-dir /opt/lab/svid-portal --expect-server spiffe://lab.example.org/backend/orders
```

접두사 규칙으로 바꾸려면 서버를 `--allow` 대신 `--allow-prefix spiffe://lab.example.org/frontend/`로 다시 실행합니다.

## 보안 고려 사항

- `--bind 0.0.0.0`은 다른 인스턴스에서 접속하게 하기 위한 값입니다. 보안 그룹에서 TCP 8443의 소스를 호출자 보안 그룹으로 제한하세요. 클라이언트 인증서가 없는 연결은 TLS 단계에서 거부됩니다.
- SVID 개인 키(`svid.0.key`)는 해당 실행 사용자만 읽을 수 있는 디렉터리에 두세요. 예제는 `install -d -m 0700 -o <사용자>`로 소유자가 해당 사용자이고 모드가 0700인 사용자별 디렉터리를 만듭니다.
- 서버는 SPIRE trust bundle의 CA만 신뢰합니다. 같은 SPIFFE ID를 적었더라도 다른 CA가 서명한 인증서는 TLS 단계에서 거부됩니다.
- 이 예제는 파일 방식으로 SVID를 받아 주기적으로 다시 읽습니다. 운영 환경에서는 Workload API를 구독하는 SPIFFE 라이브러리(예: [go-spiffe](https://github.com/spiffe/go-spiffe)), [spiffe-helper](https://github.com/spiffe/spiffe-helper), 또는 Envoy SDS 연동을 사용하세요.
- 예제 서버는 단순한 HTTP 처리만 구현합니다. 요청 크기 제한, 속도 제한, 감사 로그 저장 같은 운영 기능은 포함하지 않습니다.

## License

This sample code is made available under the MIT-0 license. See the [LICENSE](LICENSE) file.
