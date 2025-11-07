import { Controller, Logger } from '@nestjs/common';
import { TraceService } from 'nestjs-otel';
import { TranscriptService } from './transcript.service';

@Controller('transcript')
export class TranscriptController {
  private readonly logger = new Logger(TranscriptController.name);

  public constructor(
    private readonly svc: TranscriptService,
    private readonly trace: TraceService,
  ) {}

  public async lifecycle() {}
  public async notification() {}

  public async subscribe() {}
  public async reauthorize() {}
  public async transcript() {}
}
