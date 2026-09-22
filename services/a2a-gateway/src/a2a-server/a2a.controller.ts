import {
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  NotFoundException,
  Param,
  Post,
  UseGuards,
} from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';

@Controller('a2a/agents')
export class A2aController {
  @Get(':publicationId/.well-known/agent-card.json')
  public agentCard(@Param('publicationId') _publicationId: string): never {
    throw new NotFoundException('publication not found');
  }

  @Get()
  @UseGuards(KongIdentityGuard)
  public catalog(): { agents: never[] } {
    return { agents: [] };
  }

  @Post(':publicationId')
  @UseGuards(KongIdentityGuard)
  @HttpCode(HttpStatus.NOT_IMPLEMENTED)
  public jsonRpc(@Param('publicationId') _publicationId: string): { error: string } {
    return { error: 'A2A executor is not configured' };
  }
}
