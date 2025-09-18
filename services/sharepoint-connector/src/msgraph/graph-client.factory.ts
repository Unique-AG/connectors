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
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { GraphAuthenticationProvider } from './graph-authentication.service';
import { MetricsMiddleware } from './metrics.middleware';
import { TokenRefreshMiddleware } from './token-refresh.middleware';

@Injectable()
export class GraphClientFactory {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly graphAuthenticationProvider: GraphAuthenticationProvider,
  ) {}

  public createClient(): Client {
    const authenticationHandler = new AuthenticationHandler(this.graphAuthenticationProvider);
    const tokenRefreshMiddleware = new TokenRefreshMiddleware(this.graphAuthenticationProvider);
    const retryHandler = new RetryHandler(new RetryHandlerOptions());
    const redirectHandler = new RedirectHandler(new RedirectHandlerOptions());
    const telemetryHandler = new TelemetryHandler();
    const metricsMiddleware = new MetricsMiddleware();
    const httpMessageHandler = new HTTPMessageHandler();

    // Order is critical - httpMessageHandler must be last
    const middlewares: Middleware[] = [
      authenticationHandler,
      tokenRefreshMiddleware,
      retryHandler,
      redirectHandler,
      telemetryHandler,
      metricsMiddleware,
      httpMessageHandler,
    ];

    // Chain the middlewares together
    for (let i = 0; i < middlewares.length - 1; i++) {
      const currentMiddleware = middlewares[i];
      const nextMiddleware = middlewares[i + 1];

      if (currentMiddleware?.setNext && nextMiddleware) {
        currentMiddleware.setNext(nextMiddleware);
      }
    }

    const clientOptions: ClientOptions = {
      middleware: middlewares[0],
      debugLogging: this.configService.get<string>('logLevel') === 'debug',
    };

    this.logger.debug({
      msg: 'SharePoint Microsoft Graph Client created with enhanced middleware chain',
      middlewareCount: middlewares.length,
      debugLogging: clientOptions.debugLogging,
    });

    return Client.initWithMiddleware(clientOptions);
  }
}
