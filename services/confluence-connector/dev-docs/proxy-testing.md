# Confluence Connector Proxy Testing (Local)

This guide documents the local proxy testing flow used for `confluence-connector`.
It covers all three proxy authentication modes:

- `no_auth` (no authentication)
- `username_password` (Basic auth)
- `ssl_tls` (mTLS client cert)

It also includes the exact commands, expected checks, and troubleshooting steps.

---

## Prerequisites

Install the tools:

```
brew install mitmproxy stunnel openssl
```

Repo location used for certs/config in this guide:

```
/Users/your-user/code/proxy-test
```

Change it to whatever location you're using.

---

## 1) No-Auth Proxy (no_auth)

### 1.1 Start mitmproxy without authentication

```
mitmproxy --mode regular --listen-host 127.0.0.1 --listen-port 8888
```

### 1.2 Configure confluence-connector (.env)

```
PROXY_AUTH_MODE=no_auth
PROXY_PROTOCOL=http
PROXY_HOST=127.0.0.1
PROXY_PORT=8888
```

### 1.3 Trust mitmproxy CA (required for HTTPS MITM)

Mitmproxy intercepts HTTPS, so Node must trust its CA:

```
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
```

You can add this env to the dev command in `package.json` for testing simplicity:

```
    "dev": "NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem nest start",
```

### 1.4 Start the service

```
pnpm dev --filter=@unique-ag/confluence-connector
```

### 1.5 Validate traffic

In mitmproxy you should see CONNECT + HTTPS traffic to:
- `api.atlassian.com` (Cloud OAuth token endpoint)
- Confluence host(s) (e.g. `acme.atlassian.net`)
- Unique API endpoints (if in external mode)

---

## 2) Basic Auth Proxy (username_password)

### 2.1 Start mitmproxy with a fixed username/password

```
mitmproxy --mode regular --listen-host 127.0.0.1 --listen-port 8888 --proxyauth user:pass
```

### 2.2 Configure confluence-connector (.env)

```
PROXY_AUTH_MODE=username_password
PROXY_PROTOCOL=http
PROXY_HOST=127.0.0.1
PROXY_PORT=8888
PROXY_USERNAME=user
PROXY_PASSWORD=pass
```

### 2.3 Trust mitmproxy CA (required for HTTPS MITM)

Mitmproxy intercepts HTTPS, so Node must trust its CA:

```
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
```

You can add this env to the dev command in `package.json` for testing simplicity:

```
    "dev": "NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem nest start",
```

### 2.4 Start the service

```
pnpm dev --filter=@unique-ag/confluence-connector
```

### 2.5 Validate traffic

In mitmproxy you should see CONNECT + HTTPS traffic to:
- `api.atlassian.com` (Cloud OAuth token endpoint)
- Confluence host(s) (e.g. `acme.atlassian.net`)
- Unique API endpoints (if in external mode)

---

## 3) TLS Client Cert Proxy (ssl_tls)

This uses mitmproxy as the proxy, and **stunnel** as a TLS/mTLS front door.

### 3.1 Generate CA + certs (one-time)

```
mkdir -p /Users/your-user/code/proxy-test && cd /Users/your-user/code/proxy-test

# CA
openssl req -x509 -newkey rsa:2048 -days 365 -nodes \
  -keyout ca.key -out ca.pem -subj "/CN=local-proxy-ca"

# stunnel server cert (CN=localhost)
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr \
  -subj "/CN=localhost"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out server.pem -days 365

# client cert used by confluence-connector
openssl req -newkey rsa:2048 -nodes -keyout client.key -out client.csr \
  -subj "/CN=local-client"
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out client.pem -days 365
```

### 3.2 Start mitmproxy (upstream proxy)

```
mitmproxy --mode regular --listen-host 127.0.0.1 --listen-port 8888
```

### 3.3 Start stunnel (TLS front door)

Create `/Users/your-user/code/proxy-test/stunnel.conf`:

```
pid = /tmp/stunnel.pid
foreground = yes

[proxy]
accept = 127.0.0.1:8443
connect = 127.0.0.1:8888
cert = /Users/your-user/code/proxy-test/server.pem
key = /Users/your-user/code/proxy-test/server.key
CAfile = /Users/your-user/code/proxy-test/ca.pem
verify = 2
```

Run:

```
stunnel /Users/your-user/code/proxy-test/stunnel.conf
```

### 3.4 Configure confluence-connector (.env)

```
PROXY_AUTH_MODE=ssl_tls
PROXY_PROTOCOL=https
PROXY_HOST=localhost
PROXY_PORT=8443
PROXY_SSL_CERT_PATH=/Users/your-user/code/proxy-test/client.pem
PROXY_SSL_KEY_PATH=/Users/your-user/code/proxy-test/client.key
PROXY_SSL_CA_BUNDLE_PATH=/Users/your-user/code/proxy-test/ca.pem
```

### 3.5 Trust mitmproxy CA (still required)

Mitmproxy still intercepts HTTPS after the CONNECT tunnel:

```
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
```

You can add this env to the dev command in `package.json` for testing simplicity:

```
    "dev": "NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem nest start",
```

### 3.6 Start the service

```
pnpm dev --filter=@unique-ag/confluence-connector
```

---

## 4) Curl-based Verification

If you see errors in the app and no traffic in mitmproxy, you can validate proxy setup with curl
command and check if traffic shows up in mitmproxy UI.

### 4.1 No-auth proxy

```
curl -v -x http://127.0.0.1:8888 \
  --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem \
  https://api.atlassian.com/
```

### 4.2 Basic auth proxy

```
curl -v -x http://user:pass@127.0.0.1:8888 \
  --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem \
  https://api.atlassian.com/
```

### 4.3 mTLS proxy

```
curl -v -x https://localhost:8443 \
  --proxy-cacert /Users/your-user/code/proxy-test/ca.pem \
  --proxy-cert /Users/your-user/code/proxy-test/client.pem \
  --proxy-key /Users/your-user/code/proxy-test/client.key \
  --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem \
  https://api.atlassian.com/
```

---

## 5) Troubleshooting

### 5.1 mitmproxy shows no traffic
- Proxy not being used or TLS handshake is failing early.
- Verify `PROXY_AUTH_MODE` and host/port.
- Verify `ProxyService initialized` / `Created ProxyAgent` logs.
- Use curl with proxy to confirm the proxy is reachable.

### 5.2 `SSL certificate problem: unable to get local issuer certificate`
- This means the client does not trust mitmproxy's CA.
- Fix: set `NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem`

### 5.3 stunnel logs: `peer did not return a certificate`
- The client did not send a client certificate.
- Ensure `PROXY_AUTH_MODE=ssl_tls` and `PROXY_SSL_CERT_PATH/PROXY_SSL_KEY_PATH` are set.
- Ensure proxy TLS settings are on the proxy connection (not target connection).

### 5.4 `SSL: certificate subject name 'localhost' does not match target host name '127.0.0.1'`
- Use `localhost` for the proxy host, or regenerate server cert with SAN for `127.0.0.1`.

---

## 6) Notes

- Proxy env vars align with the [Unique Python
  implementation](https://github.com/Unique-AG/ai/blob/5fe47d97b79baad60d53f65f068874320baa14c2/tool_packages/unique_web_search/src/unique_web_search/services/client/proxy_config.py)
  as of 29.01.2026:
  `PROXY_SSL_CERT_PATH`, `PROXY_SSL_KEY_PATH`, `PROXY_SSL_CA_BUNDLE_PATH`.
- The CA bundle is optional, but required when your HTTPS proxy uses a private/self-signed CA.
- `unique.serviceAuthMode=external` routes Unique API calls through the proxy. When testing, don't
  forget to test that it still happens.
