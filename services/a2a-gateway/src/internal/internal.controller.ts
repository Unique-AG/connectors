import { Controller, Get, UseGuards } from '@nestjs/common';
import { ClusterIdentityGuard } from '../auth/identity.guard.js';

@Controller('internal')
@UseGuards(ClusterIdentityGuard)
export class InternalController {
  @Get('capabilities')
  public capabilities() {
    return {
      version: '0.0.0',
      protocolVersions: ['1.0'],
      features: {
        inbound: false,
        outbound: false,
      },
    } as const;
  }
}
