import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import type { CookieOptions } from 'express';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

export interface FlowCookie {
  name: string;
  value: string;
  options: CookieOptions;
}

/**
 * Binds an authorization flow to the browser that started it with a signed cookie, from which
 * the consent form's CSRF token is derived.
 */
@Injectable()
export class FlowBindingService {
  private readonly secure: boolean;

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {
    // Browsers drop Secure cookies on plain-http origins other than localhost, which only
    // happens in local development.
    this.secure = new URL(options.serverUrl).protocol === 'https:';
  }

  public createBinding(sessionId: string): { cookie: FlowCookie; csrfToken: string } {
    const binding = randomBytes(32).toString('base64url');
    const value = `${binding}.${this.sign(`flow:${sessionId}:${binding}`)}`;

    return {
      cookie: {
        name: this.cookieName(sessionId),
        value,
        options: { ...this.baseCookieOptions(), maxAge: this.options.oauthSessionExpiresIn },
      },
      csrfToken: this.csrfToken(sessionId, value),
    };
  }

  public clearedCookie(sessionId: string): Omit<FlowCookie, 'value'> {
    return { name: this.cookieName(sessionId), options: this.baseCookieOptions() };
  }

  /** Returns the cookie value when the browser holds a validly signed cookie for the session. */
  public readBinding(cookieHeader: string | undefined, sessionId: string): string | undefined {
    const value = readCookie(cookieHeader, this.cookieName(sessionId));
    if (!value) {
      return undefined;
    }

    const [binding, signature, ...rest] = value.split('.');
    if (!binding || !signature || rest.length > 0) {
      return undefined;
    }

    return safeEqual(signature, this.sign(`flow:${sessionId}:${binding}`)) ? value : undefined;
  }

  public isValidCsrfToken(sessionId: string, cookieValue: string, submitted: string): boolean {
    return safeEqual(submitted, this.csrfToken(sessionId, cookieValue));
  }

  private csrfToken(sessionId: string, cookieValue: string): string {
    return this.sign(`consent:${sessionId}:${cookieValue}`);
  }

  private cookieName(sessionId: string): string {
    // __Host- pins the cookie to this exact host, so a sibling subdomain cannot plant one.
    const prefix = this.secure ? '__Host-' : '';
    const digest = createHash('sha256').update(sessionId).digest('hex').slice(0, 16);
    return `${prefix}mcp_oauth_flow_${digest}`;
  }

  private baseCookieOptions(): CookieOptions {
    return { httpOnly: true, secure: this.secure, sameSite: 'lax', path: '/' };
  }

  private sign(payload: string): string {
    return createHmac('sha256', this.options.hmacSecret).update(payload).digest('base64url');
  }
}

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

function readCookie(header: string | undefined, name: string): string | undefined {
  for (const part of header?.split(';') ?? []) {
    const separator = part.indexOf('=');
    if (separator !== -1 && part.slice(0, separator).trim() === name) {
      return part.slice(separator + 1).trim();
    }
  }
  return undefined;
}
