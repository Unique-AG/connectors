/** biome-ignore-all lint/suspicious/noExplicitAny: Mock implementation needs access to passport internals */
export interface MockStrategyOptions {
  user?: unknown;
  failureMessage?: string;
  passReqToCallback?: boolean;
}

/**
 * Custom mock passport strategy for testing OAuth flows.
 * This simulates a real OAuth2 strategy behavior for testing.
 */
export class MockPassportStrategy {
  public name: string;
  private readonly options: MockStrategyOptions;
  private readonly verify: (
    accessToken: string,
    refreshToken: string,
    profile: unknown,
    done: (error: unknown, user: unknown) => void,
  ) => void;

  public constructor(
    options: MockStrategyOptions,
    verify: typeof MockPassportStrategy.prototype.verify,
  ) {
    this.name = 'oauth-provider';
    this.options = options;
    this.verify = verify;
  }

  // Simulate passport authenticate method for testing
  // This is called by passport.authenticate() and needs to return a middleware function
  public authenticate(req: any, options: any = {}) {
    // Store req and res for later use in success/fail/redirect methods
    (this as any).req = req;
    (this as any).res = req.res;

    // Check if this is the initial authorization request or the callback
    const isCallback = req.url?.includes('/oauth/callback') || req.query?.code;

    if (!isCallback) {
      // This is the initial authorization - redirect to callback with state
      const callbackUrl = new URL('/oauth/callback', 'http://mock-idp-server.example');
      if (options.state) callbackUrl.searchParams.set('state', options.state);
      callbackUrl.searchParams.set('code', 'mock-provider-code');

      return this.redirect(callbackUrl.toString());
    }

    // This is the callback - simulate successful authentication
    const mockProfile = this.options.user || {
      id: 'user-123',
      username: 'testuser',
      displayName: 'Test User',
      emails: [{ value: 'test@example.com' }],
    };

    // Simulate successful authentication by calling the verify callback
    this.verify('mock-access-token', 'mock-refresh-token', mockProfile, (error, user) => {
      if (error) return this.error(error);
      if (!user) return this.fail(this.options.failureMessage || 'Authentication failed');
      return this.success(user);
    });
  }

  private success(user: any, info?: any) {
    const req = (this as any).req;
    req.user = user;

    const callback = (this as any)._callback;
    if (callback && typeof callback === 'function') callback(null, user, info);
  }

  private fail(challenge?: any, _status?: number) {
    const callback = (this as any)._callback;
    if (callback && typeof callback === 'function') {
      callback(null, false, {
        message: challenge || this.options.failureMessage || 'Authentication failed',
      });
    } else if (this.options.failureMessage) {
      throw new Error(this.options.failureMessage);
    }
  }

  private redirect(url: string, status?: number) {
    const res = (this as any).res;
    if (res) res.redirect(status || 302, url);
  }

  private error(err: any) {
    const callback = (this as any)._callback;
    if (callback && typeof callback === 'function') {
      callback(err);
    } else {
      throw err;
    }
  }
}
