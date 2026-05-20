import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import {
  AuthenticationHandler,
  Client,
  ClientOptions,
  HTTPMessageHandler,
  type Middleware,
  RedirectHandler,
  RedirectHandlerOptions,
  RetryHandler,
  RetryHandlerOptions,
  TelemetryHandler,
} from '@microsoft/microsoft-graph-client';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { and, desc, eq, ilike, isNotNull, notInArray } from 'drizzle-orm';
import { MetricService } from 'nestjs-otel';
import type { AppConfigNamespaced, MicrosoftConfigNamespaced } from '~/config';
import { SCOPES } from '../auth/microsoft.provider';
import { DRIZZLE, DrizzleDatabase } from '../db/drizzle.module';
import { userProfiles } from '../db/schema';
import { MetricsMiddleware } from './metrics.middleware';
import { TokenProvider } from './token.provider';
import { TokenRefreshMiddleware } from './token-refresh.middleware';

@Injectable()
export class GraphClientFactory {
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly scopes: string[];

  public constructor(
    private readonly configService: ConfigService<
      AppConfigNamespaced & MicrosoftConfigNamespaced,
      true
    >,
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    private readonly encryptionService: AesGcmEncryptionService,
    private readonly metricService: MetricService,
  ) {
    this.clientId = this.configService.get('microsoft.clientId', {
      infer: true,
    });
    this.clientSecret = this.configService.get('microsoft.clientSecret', {
      infer: true,
    }).value;
    this.scopes = SCOPES;
  }

  // Use this when reading a MS Graph resource that any authenticated user can access (e.g. listing
  // all users via User.Read.All). Do NOT use it for mailbox-specific operations — those require a
  // client scoped to a particular user via createClientForUser.
  public async createClientForAnyAuthorizedUser(
    excludeIds?: string[],
    domain?: string,
  ): Promise<{ client: Client; userId: string } | null> {
    const profile = await this.drizzle.query.userProfiles.findFirst({
      where: and(
        // We filter only users which can get an oauth token
        eq(userProfiles.source, 'oauth'),
        isNotNull(userProfiles.accessToken),
        excludeIds && excludeIds.length > 0 ? notInArray(userProfiles.id, excludeIds) : undefined,
        domain ? ilike(userProfiles.email, `%@${domain}`) : undefined,
      ),
      // We order by updatedAt descending so that we minize the chance of getting a deactivated user
      orderBy: (t) => desc(t.updatedAt),
      columns: { id: true },
    });
    if (!profile) {
      return null;
    }
    return { userId: profile.id, client: this.createClientForUser(profile.id) };
  }

  public createClientForUser(userProfileId: string): Client {
    const tokenProvider = new TokenProvider(
      {
        userProfileId,
        clientId: this.clientId,
        clientSecret: this.clientSecret,
        scopes: this.scopes,
      },
      {
        drizzle: this.drizzle,
        encryptionService: this.encryptionService,
      },
    );

    // We replicate the default middleware chain from the Microsoft Graph SDK
    // https://github.com/microsoftgraph/msgraph-sdk-javascript/blob/dev/src/middleware/MiddlewareFactory.ts#L43
    const authenticationHandler = new AuthenticationHandler(tokenProvider);
    const retryHandler = new RetryHandler(new RetryHandlerOptions());
    const redirectHandler = new RedirectHandler(new RedirectHandlerOptions());
    const telemetryHandler = new TelemetryHandler();
    const httpMessageHandler = new HTTPMessageHandler();

    // Create our custom middlewares
    const tokenRefreshMiddleware = new TokenRefreshMiddleware(tokenProvider, userProfileId);
    const metricsMiddleware = new MetricsMiddleware(this.metricService);

    // !The order of the middlewares is important.
    // The httpMessageHandler must be the last middleware in the chain as it does not call setNext.
    const middlewares: Middleware[] = [
      authenticationHandler,
      tokenRefreshMiddleware,
      retryHandler,
      redirectHandler,
      telemetryHandler,
      metricsMiddleware,
      httpMessageHandler,
    ];

    // Chain the middlewares together by setting next on each one
    for (let i = 0; i < middlewares.length - 1; i++) {
      const currentMiddleware = middlewares[i];
      const nextMiddleware = middlewares[i + 1];

      if (currentMiddleware?.setNext && nextMiddleware) {
        currentMiddleware.setNext(nextMiddleware);
      }
    }

    // Pass the first middleware in the chain to initialize the client
    const clientOptions: ClientOptions = {
      middleware: middlewares[0],
      debugLogging: this.configService.get('app.isDebuggingOn', {
        infer: true,
      }),
    };

    return Client.initWithMiddleware(clientOptions);
  }
}
