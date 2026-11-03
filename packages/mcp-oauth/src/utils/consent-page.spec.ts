import { describe, expect, it } from 'vitest';
import { CONSENT_PAGE_HEADERS, renderConsentPage } from './consent-page';

const baseInput = {
  clientName: 'Claude Desktop',
  redirectUri: 'https://claude.ai/api/mcp/auth_callback',
  resourceName: 'teams.example.com',
  formAction: 'https://teams.example.com/auth/consent',
  sessionId: 'session-123',
  csrfToken: 'csrf-456',
};

describe('renderConsentPage', () => {
  it('names the client and shows the redirect host', () => {
    const html = renderConsentPage(baseInput);

    expect(html).toContain('<strong>Claude Desktop</strong> wants to access teams.example.com');
    expect(html).toContain('<strong>claude.ai</strong>');
    expect(html).toContain('https://claude.ai/api/mcp/auth_callback');
  });

  it('posts the session and CSRF token to the consent endpoint', () => {
    const html = renderConsentPage(baseInput);

    expect(html).toContain('<form method="post" action="https://teams.example.com/auth/consent">');
    expect(html).toContain('name="session_id" value="session-123"');
    expect(html).toContain('name="csrf_token" value="csrf-456"');
    expect(html).toContain('name="decision" value="approve"');
    expect(html).toContain('name="decision" value="deny"');
  });

  it('escapes client-controlled strings', () => {
    const html = renderConsentPage({
      ...baseInput,
      clientName: `<script>alert('x')</script>"&`,
      redirectUri: 'https://evil.example/cb?a="><img src=x>',
    });

    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;&quot;&amp;');
  });

  it('shows the scheme for a redirect URI without a host', () => {
    const html = renderConsentPage({ ...baseInput, redirectUri: 'myapp:/oauth/callback' });

    expect(html).toContain('<strong>myapp:</strong>');
  });

  it('loads no external resources', () => {
    const html = renderConsentPage(baseInput);

    expect(html).not.toMatch(/<(script|link|img|iframe)\b/);
  });
});

describe('CONSENT_PAGE_HEADERS', () => {
  it('forbids framing and every resource except inline styles', () => {
    expect(CONSENT_PAGE_HEADERS['X-Frame-Options']).toBe('DENY');
    expect(CONSENT_PAGE_HEADERS['Content-Security-Policy']).toBe(
      "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
    );
  });
});
