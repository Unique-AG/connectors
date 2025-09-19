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
import { MetricService } from 'nestjs-otel';
import { TypeID } from 'typeid-js';
import { AppConfig, AppSettings } from '../app-settings.enum';
import { SCOPES } from '../auth/microsoft.provider';
import { DRIZZLE, DrizzleDatabase } from '../drizzle/drizzle.module';
import { MetricsMiddleware } from './metrics.middleware';
import { TokenProvider } from './token.provider';
import { TokenRefreshMiddleware } from './token-refresh.middleware';

@Injectable()
export class GraphClientFactory {
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly scopes: string[];

  public constructor(
    private readonly configService: ConfigService<AppConfig, true>,
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    private readonly encryptionService: AesGcmEncryptionService,
    private readonly metricService: MetricService,
  ) {
    this.clientId = this.configService.get(AppSettings.MICROSOFT_CLIENT_ID);
    this.clientSecret = this.configService.get(AppSettings.MICROSOFT_CLIENT_SECRET);
    this.scopes = SCOPES;
  }

  public createClientForUser(userProfileId: TypeID<'user_profile'>): Client {
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

      if (currentMiddleware?.setNext && nextMiddleware) currentMiddleware.setNext(nextMiddleware);
    }

    // Pass the first middleware in the chain to initialize the client
    const clientOptions: ClientOptions = {
      middleware: middlewares[0],
      debugLogging: this.configService.get(AppSettings.LOG_LEVEL, { infer: true }) === 'debug',
    };

    return Client.initWithMiddleware(clientOptions);
  }
}
