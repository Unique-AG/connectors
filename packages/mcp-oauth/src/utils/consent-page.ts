/**
 * `form-action` is left out on purpose: Chrome enforces it on every redirect that follows a form
 * submission, so it would block the hop to the identity provider and the final redirect to
 * clients on custom schemes such as `cursor://`. The form posts to an absolute same-origin URL
 * and `base-uri 'none'` keeps injected markup from retargeting it.
 */
export const CONSENT_PAGE_HEADERS = {
  'Content-Type': 'text/html; charset=utf-8',
  'Content-Security-Policy':
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
  'X-Frame-Options': 'DENY',
  'X-Content-Type-Options': 'nosniff',
  'Cache-Control': 'no-store',
  'Referrer-Policy': 'no-referrer',
};

export interface ConsentPageInput {
  clientName: string;
  redirectUri: string;
  resourceName: string;
  formAction: string;
  sessionId: string;
  csrfToken: string;
}

export function renderConsentPage(input: ConsentPageInput): string {
  const clientName = escapeHtml(input.clientName);
  const redirectHost = escapeHtml(redirectTarget(input.redirectUri));
  const redirectUri = escapeHtml(input.redirectUri);
  const resourceName = escapeHtml(input.resourceName);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Allow access to ${resourceName}?</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; font-family: system-ui, sans-serif; background: #02161d; color: #fff; }
main { width: 100%; max-width: 30rem; background: #03212b; border-radius: 1rem; padding: 2rem 1.75rem; box-shadow: 0 16px 40px rgba(0, 0, 0, 0.35); }
h1 { margin: 0 0 1rem; font-size: 1.25rem; line-height: 1.4; }
p { margin: 0 0 1rem; color: #92aab1; font-size: 0.9rem; line-height: 1.5; }
.target { margin: 0 0 1rem; padding: 0.85rem 1rem; border: 1px solid #e0a854; border-radius: 0.5rem; background: #05313f; }
.target strong { display: block; color: #fff; font-size: 1.1rem; word-break: break-all; }
.target small { display: block; margin-top: 0.35rem; color: #92aab1; word-break: break-all; }
.actions { display: flex; gap: 0.75rem; margin-top: 1.5rem; }
button { flex: 1; padding: 0.7rem 1rem; border: 0; border-radius: 0.5rem; font: inherit; font-weight: 600; cursor: pointer; }
.approve { background: #1fb7ea; color: #fff; }
.deny { background: #05313f; color: #fff; border: 1px solid #92aab1; }
</style>
</head>
<body>
<main>
<h1><strong>${clientName}</strong> wants to access ${resourceName} on your behalf</h1>
<p>If you approve, you sign in next and your access is sent to:</p>
<div class="target">
<strong>${redirectHost}</strong>
<small>${redirectUri}</small>
</div>
<p>Only approve if you started this connection yourself and you recognise this address. Anyone who receives this access can act as you.</p>
<form method="post" action="${escapeHtml(input.formAction)}">
<input type="hidden" name="session_id" value="${escapeHtml(input.sessionId)}">
<input type="hidden" name="csrf_token" value="${escapeHtml(input.csrfToken)}">
<div class="actions">
<button type="submit" name="decision" value="deny" class="deny">Deny</button>
<button type="submit" name="decision" value="approve" class="approve">Approve</button>
</div>
</form>
</main>
</body>
</html>
`;
}

function redirectTarget(redirectUri: string): string {
  const url = new URL(redirectUri);
  return url.host || url.protocol;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
