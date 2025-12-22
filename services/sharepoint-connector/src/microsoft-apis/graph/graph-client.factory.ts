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
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, type Histogram } from '@opentelemetry/api';
import type { Config } from '../../config';
import { TenantConfigLoaderService } from '../../config/tenant-config-loader.service';
import {
  SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
  SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
  SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
} from '../../metrics';
import { GraphAuthenticationService } from './middlewares/graph-authentication.service';
import { MetricsMiddleware } from './middlewares/metrics.middleware';
import { TokenRefreshMiddleware } from './middlewares/token-refresh.middleware';

@Injectable()
export class GraphClientFactory {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphAuthenticationService: GraphAuthenticationService,
    private readonly configService: ConfigService<Config, true>,
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
    @Inject(SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS)
    private readonly spcGraphApiRequestDurationSeconds: Histogram,
    @Inject(SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL)
    private readonly spcGraphApiThrottleEventsTotal: Counter,
    @Inject(SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL)
    private readonly spcGraphApiSlowRequestsTotal: Counter,
  ) {}

  public createClient(): Client {
    const authenticationHandler = new AuthenticationHandler(this.graphAuthenticationService);
    const tokenRefreshMiddleware = new TokenRefreshMiddleware(this.graphAuthenticationService);
    const retryHandler = new RetryHandler(new RetryHandlerOptions());
    const redirectHandler = new RedirectHandler(new RedirectHandlerOptions());
    const telemetryHandler = new TelemetryHandler();
    const metricsMiddleware = new MetricsMiddleware(
      this.spcGraphApiRequestDurationSeconds,
      this.spcGraphApiThrottleEventsTotal,
      this.spcGraphApiSlowRequestsTotal,
      this.configService,
      this.tenantConfigLoaderService,
    );
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
      debugLogging: false, // else the client will log requests without a level
    };

    this.logger.debug({
      msg: 'SharePoint Microsoft Graph Client created with enhanced middleware chain',
      middlewareCount: middlewares.length,
      debugLogging: clientOptions.debugLogging,
    });

    return Client.initWithMiddleware(clientOptions);
  }
}
