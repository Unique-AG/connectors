import { Global, Module } from '@nestjs/common';
import { GATEWAY_CONFIG, loadConfig } from './config.js';

@Global()
@Module({
  providers: [{ provide: GATEWAY_CONFIG, useFactory: loadConfig }],
  exports: [GATEWAY_CONFIG],
})
export class GatewayConfigModule {}
