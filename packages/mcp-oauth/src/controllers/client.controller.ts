import { Body, Controller, Post, UseGuards, UsePipes } from '@nestjs/common';
import { ThrottlerGuard } from '@nestjs/throttler';
import { ZodValidationPipe } from 'nestjs-zod';
import { OAUTH_ENDPOINTS, OAUTH_FALLBACK_ENDPOINTS } from '../constants/oauth.constants';
import { RegisterClientDto } from '../dtos/register-client.dto';
import { ClientService } from '../services/client.service';
import { MetricService } from '../services/metric.service';

@Controller()
@UseGuards(ThrottlerGuard)
export class ClientController {
  public constructor(
    private readonly clientService: ClientService,
    private readonly metricService: MetricService,
  ) {}

  @Post([OAUTH_ENDPOINTS.register, OAUTH_FALLBACK_ENDPOINTS.register])
  @UsePipes(ZodValidationPipe)
  public async registerClient(@Body() registerClientDto: RegisterClientDto) {
    this.metricService.incrementClientsRegistered();
    return this.clientService.registerClient(registerClientDto);
  }
}
