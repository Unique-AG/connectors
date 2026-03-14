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
import type { AppConfigNamespaced, MicrosoftConfigNamespaced } from '~/config';
import { SCOPES } from '../auth/microsoft.provider';
import { DRIZZLE, DrizzleDatabase } from '../drizzle/drizzle.module';
import { GlobalThrottleMiddleware } from './global-throttle.middleware';
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
    this.clientId = this.configService.get('microsoft.clientId', { infer: true });
    this.clientSecret = this.configService.get('microsoft.clientSecret', { infer: true }).value;
    this.scopes = SCOPES;
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

    const authenticationHandler = new AuthenticationHandler(tokenProvider);
    const globalThrottle = new GlobalThrottleMiddleware(userProfileId);
    const retryHandler = new RetryHandler(new RetryHandlerOptions(5, 5));
    const redirectHandler = new RedirectHandler(new RedirectHandlerOptions());
    const telemetryHandler = new TelemetryHandler();
    const httpMessageHandler = new HTTPMessageHandler();
    const tokenRefreshMiddleware = new TokenRefreshMiddleware(tokenProvider, userProfileId);
    const metricsMiddleware = new MetricsMiddleware(this.metricService);

    const middlewares: Middleware[] = [
      authenticationHandler,
      tokenRefreshMiddleware,
      globalThrottle,
      metricsMiddleware,
      retryHandler,
      redirectHandler,
      telemetryHandler,
      httpMessageHandler,
    ];

    for (let i = 0; i < middlewares.length - 1; i++) {
      const currentMiddleware = middlewares[i];
      const nextMiddleware = middlewares[i + 1];
      if (currentMiddleware?.setNext && nextMiddleware) currentMiddleware.setNext(nextMiddleware);
    }

    const clientOptions: ClientOptions = {
      middleware: middlewares[0],
      debugLogging: this.configService.get('app.isDebuggingOn', { infer: true }),
    };

    return Client.initWithMiddleware(clientOptions);
  }
}
