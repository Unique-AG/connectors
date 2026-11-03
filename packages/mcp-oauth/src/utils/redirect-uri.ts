const LOOPBACK_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]']);

const DENIED_SCHEMES = new Set(['javascript', 'data', 'file', 'vbscript', 'blob', 'about']);

// Native MCP clients that register a single-word private-use scheme (RFC 8252 §7.1).
const ALLOWED_NATIVE_SCHEMES = new Set(['cursor', 'vscode', 'vscode-insiders']);

export function isLoopbackHostname(hostname: string): boolean {
  return LOOPBACK_HOSTNAMES.has(hostname);
}

function parseUrl(value: string): URL | undefined {
  try {
    return new URL(value);
  } catch {
    return undefined;
  }
}

export function isAllowedRedirectUri(value: string): boolean {
  const url = parseUrl(value);
  if (!url || value.includes('#')) {
    return false;
  }

  const scheme = url.protocol.slice(0, -1);
  if (DENIED_SCHEMES.has(scheme)) {
    return false;
  }
  if (scheme === 'https') {
    return true;
  }
  if (scheme === 'http') {
    return isLoopbackHostname(url.hostname);
  }
  return scheme.includes('.') || ALLOWED_NATIVE_SCHEMES.has(scheme);
}
