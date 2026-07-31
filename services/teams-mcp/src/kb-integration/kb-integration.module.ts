import { type DynamicModule, Module } from '@nestjs/common';
import { TranscriptModule } from '~/transcript/transcript.module';
import { KbIntegrationConfigModule } from './kb-integration-config.module';

export function shouldRegisterKbIntegrationModule(): boolean {
  return process.env.UNIQUE_INTEGRATION === 'enabled';
}
/**
 * Optional knowledge-base integration surface (transcript ingestion tools +
 * Unique-backed webhook/ingestion pipeline). Registered only when
 * UNIQUE_INTEGRATION=enabled so chat-only deployments never expose KB tools.
 */
@Module({})
export class KbIntegrationModule {}

export function registerKbIntegrationModule(): DynamicModule[] {
  if (!shouldRegisterKbIntegrationModule()) {
    return [];
  }

  return [
    KbIntegrationConfigModule.forRoot(),
    {
      module: KbIntegrationModule,
      imports: [TranscriptModule],
    },
  ];
}
