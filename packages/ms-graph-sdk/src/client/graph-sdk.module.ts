import { Module } from '@nestjs/common';
import { GraphClientService } from './graph-client.service';
import { ConfigurableModuleClass } from './graph-sdk.module.options';

@Module({
  providers: [GraphClientService],
  exports: [GraphClientService],
})
export class GraphSdkModule extends ConfigurableModuleClass {}
