import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { IngestRequestedEvent, PipelineEvents } from './pipeline.events';

@Injectable()
export class OrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly amqpConnection: AmqpConnection) {}

  @OnEvent(PipelineEvents.IngestRequested)
  public async ingest(event: IngestRequestedEvent) {
    const { userProfileId, folderId, message } = event;

    await this.amqpConnection.publish('email.pipeline', 'email.ingest', {
      message,
      userProfileId: userProfileId.toString(),
      folderId,
    });
  }
}
