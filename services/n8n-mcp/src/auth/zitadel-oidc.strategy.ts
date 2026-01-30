import { IncomingMessage } from 'node:http';
import { Request } from 'express';
import * as jwt from 'jsonwebtoken';
import { Client, Issuer, TokenSet, UserinfoResponse } from 'openid-client';
import { Strategy } from 'passport-strategy';

export interface ZitadelOIDCStrategyOptions {
  issuer: string;
  clientID: string;
  clientSecret: string;
  callbackURL: string;
  scope?: string[];
  requiredRole?: string;
  passReqToCallback?: boolean;
}

export interface ZitadelProfile {
  id: string;
  username: string;
  email?: string;
  displayName?: string;
  name?: string;
  given_name?: string;
  family_name?: string;
  preferred_username?: string;
  roles?: string[];
  raw: UserinfoResponse;
}

export type ZitadelStrategyVerifyCallback = (
  error: Error | null,
  user?: ZitadelProfile | false,
  info?: any,
) => void;

export type ZitadelStrategyVerifyFunction = (
  accessToken: string,
  refreshToken: string,
  profile: ZitadelProfile,
  done: ZitadelStrategyVerifyCallback,
) => void;

export type ZitadelStrategyVerifyFunctionWithRequest = (
  req: IncomingMessage,
  accessToken: string,
  refreshToken: string,
  profile: ZitadelProfile,
  done: ZitadelStrategyVerifyCallback,
) => void;

export class ZitadelOIDCStrategy extends Strategy {
  public name = 'zitadel-oidc';
  private client?: Client;
  private issuer?: Issuer<Client>;
  private readonly options: ZitadelOIDCStrategyOptions;
  private readonly verify: ZitadelStrategyVerifyFunction | ZitadelStrategyVerifyFunctionWithRequest;
  private clientInitPromise?: Promise<void>;

  public constructor(
    options: ZitadelOIDCStrategyOptions,
    verify: ZitadelStrategyVerifyFunction | ZitadelStrategyVerifyFunctionWithRequest,
  ) {
    super();
    this.options = {
      scope: ['openid', 'profile', 'email'],
      ...options,
    };
    this.verify = verify;
    this.clientInitPromise = this.initializeClient();
  }

  public authenticate(req: Request, options?: any): void {
    this.clientInitPromise
      ?.then(() => {
        const { code, state, error } = req.query;

        if (error) return this.fail({ message: `OAuth error: ${error}` }, 401);

        if (!code) {
          const authState = options?.state;
          return this.redirectToAuth(authState);
        }

        if (typeof code !== 'string') return this.fail({ message: 'Invalid code parameter' }, 401);
        if (typeof state !== 'string')
          return this.fail({ message: 'Invalid state parameter' }, 401);

        this.handleCallback(req, code, state).catch((err) => {
          this.error(err as Error);
        });
      })
      .catch((err) => {
        this.error(err as Error);
      });
  }

  private async initializeClient(): Promise<void> {
    try {
      this.issuer = await Issuer.discover(this.options.issuer);
      this.client = new this.issuer.Client({
        client_id: this.options.clientID,
        client_secret: this.options.clientSecret,
        redirect_uris: [this.options.callbackURL],
        response_types: ['code'],
      });
    } catch (error) {
      throw new Error(`Failed to initialize OIDC client: ${error}`);
    }
  }

  private redirectToAuth(oauthState?: string): void {
    if (!this.client) throw new Error('OIDC client not initialized');

    const authUrl = this.client.authorizationUrl({
      scope: this.options.scope?.join(' ') || 'openid profile email',
      state: oauthState || '',
    });

    this.redirect(authUrl);
  }

  private async handleCallback(req: Request, code: string, state: string): Promise<void> {
    if (!this.client) throw new Error('OIDC client not initialized');

    try {
      const tokenSet: TokenSet = await this.client.callback(
        this.options.callbackURL,
        { code, state },
        { state },
      );

      if (!tokenSet.access_token) return this.fail({ message: 'Invalid access token' }, 401);
      const userinfo = await this.client.userinfo(tokenSet.access_token);

      const roles = await this.extractRoles(tokenSet);

      if (this.options.requiredRole && !roles.includes(this.options.requiredRole)) {
        return this.fail(
          { message: `Required role '${this.options.requiredRole}' not found` },
          401,
        );
      }

      const profile: ZitadelProfile = {
        id: userinfo.sub,
        username: userinfo.preferred_username || userinfo.sub,
        email: userinfo.email,
        displayName: userinfo.name || userinfo.preferred_username,
        name: userinfo.name,
        given_name: userinfo.given_name,
        family_name: userinfo.family_name,
        preferred_username: userinfo.preferred_username,
        roles,
        raw: userinfo,
      };

      const done: ZitadelStrategyVerifyCallback = (error, user, info) => {
        if (error) return this.error(error);
        if (!user) return this.fail(info);

        return this.success(user, info);
      };

      if (this.options.passReqToCallback) {
        (this.verify as ZitadelStrategyVerifyFunctionWithRequest)(
          req,
          tokenSet.access_token,
          tokenSet.refresh_token || '',
          profile,
          done,
        );
      } else {
        (this.verify as ZitadelStrategyVerifyFunction)(
          tokenSet.access_token,
          tokenSet.refresh_token || '',
          profile,
          done,
        );
      }
    } catch (error) {
      console.log('error', error);
      this.fail({ message: `Token exchange failed: ${error}` }, 401);
    }
  }

  private async extractRoles(tokenSet: TokenSet): Promise<string[]> {
    const roles: string[] = [];

    try {
      if (tokenSet.id_token) {
        const decoded = jwt.decode(tokenSet.id_token, { complete: true });
        if (decoded && typeof decoded === 'object' && decoded.payload) {
          const payload = decoded.payload as Record<string, unknown>;

          if (payload.roles && Array.isArray(payload.roles)) {
            roles.push(...payload.roles);
          }
          if (
            payload['urn:zitadel:iam:org:project:roles'] &&
            typeof payload['urn:zitadel:iam:org:project:roles'] === 'object'
          ) {
            roles.push(...Object.keys(payload['urn:zitadel:iam:org:project:roles']));
          }
        }
      }

      if (tokenSet.access_token && roles.length === 0) {
        const decoded = jwt.decode(tokenSet.access_token, { complete: true });
        if (decoded && typeof decoded === 'object' && decoded.payload) {
          const payload = decoded.payload as Record<string, unknown>;

          if (payload.roles && Array.isArray(payload.roles)) {
            roles.push(...payload.roles);
          }
          if (
            payload['urn:zitadel:iam:org:project:roles'] &&
            typeof payload['urn:zitadel:iam:org:project:roles'] === 'object'
          ) {
            roles.push(...Object.keys(payload['urn:zitadel:iam:org:project:roles']));
          }
        }
      }
    } catch (error) {
      console.warn('Failed to extract roles from tokens:', error);
    }

    return roles;
  }
}
