import {
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  ServiceUnavailableException,
  VERSION_NEUTRAL,
} from '@nestjs/common';
import { ApiExcludeEndpoint, ApiTags } from '@nestjs/swagger';
import type { UptimeSummary } from './up.interfaces';
import { UpRegistryService } from './up.registry';

@Controller({ path: 'up', version: VERSION_NEUTRAL })
@ApiTags('Monitoring')
export class UpController {
  public constructor(private readonly registry: UpRegistryService) {}

  @Get()
  @ApiExcludeEndpoint()
  @HttpCode(HttpStatus.OK)
  public async up(): Promise<UptimeSummary> {
    const summary = await this.registry.runAllChecks();
    if (summary.status === 'down') {
      throw new ServiceUnavailableException(summary);
    }
    return summary;
  }
}
