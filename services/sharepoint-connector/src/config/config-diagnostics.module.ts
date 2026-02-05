import { Global, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ConfigDiagnosticsService } from './config-diagnostics.service';

@Global()
@Module({
  imports: [ConfigModule],
  providers: [ConfigDiagnosticsService],
  exports: [ConfigDiagnosticsService],
})
export class ConfigDiagnosticsModule {}
