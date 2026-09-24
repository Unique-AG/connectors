import { Controller, Get, Inject } from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

@Controller('.well-known')
export class OAuthDiscoveryController {
  public constructor(@Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig) {}

  @Get('oauth-protected-resource/a2a')
  public metadata() {
    return {
      resource: new URL('a2a', this.config.publicBaseUrl).toString(),
      authorization_servers: [this.config.zitadelIssuer.toString().replace(/\/$/, '')],
      bearer_methods_supported: ['header'],
    };
  }
}
