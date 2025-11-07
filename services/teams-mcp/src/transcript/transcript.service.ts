import { Injectable, Logger } from '@nestjs/common';
import { TraceService } from 'nestjs-otel';

@Injectable()
export class TranscriptService {
  private readonly logger = new Logger(TranscriptService.name);

  public constructor(private readonly trace: TraceService) {}

  public async enqueueSubscribe() {}
  public async enqueueReauthorize() {}
  public async enqueueTranscript() {}

  public async subscribe() {}
  public async reauthorize() {}
  public async transcript() {}
}
