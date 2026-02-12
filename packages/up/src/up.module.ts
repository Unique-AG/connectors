import { Module } from '@nestjs/common';
import { DiscoveryModule } from '@nestjs/core';
import { UpController } from './up.controller';
import { UpRegistryService } from './up.registry';

@Module({
  imports: [DiscoveryModule],
  controllers: [UpController],
  providers: [UpRegistryService],
  exports: [UpRegistryService],
})
export class UpModule {}
