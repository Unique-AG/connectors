import { Controller, Get, UseGuards } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';

@Controller('management')
@UseGuards(KongIdentityGuard)
export class ManagementController {
  @Get('capabilities')
  public capabilities(): { configured: false } {
    return { configured: false };
  }
}
