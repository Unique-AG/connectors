import { Module } from '@nestjs/common';
import { ConfigurableModuleClass } from './proxy.module-definition';
import { ProxyService } from './proxy.service';

@Module({
  providers: [ProxyService],
  exports: [ProxyService],
})
export class ProxyModule extends ConfigurableModuleClass {}
