import { Global, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { GATEWAY_CONFIG, loadConfig } from './config.js';

@Global()
@Module({
  imports: [ConfigModule.forRoot()],
  providers: [{ provide: GATEWAY_CONFIG, useFactory: loadConfig }],
  exports: [GATEWAY_CONFIG],
})
export class GatewayConfigModule {}
