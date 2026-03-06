import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { traceAttrs } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GraphMessageFields, graphMessageSchema } from './dtos/microsoft-graph.dtos';

@Injectable()
export class GetMessageDetailsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run({ userProfileId, messageId }: { userProfileId: string; messageId: string }) {
    traceAttrs({ message_id: messageId });
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const messageRaw = await client
      .api(`me/messages/${messageId}`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .select(GraphMessageFields)
      .get();
    this.logger.log({ msg: 'Received data for messageId', userProfileId, messageId });

    const output = graphMessageSchema.parse(messageRaw);
    this.logger.log({ msg: 'Parsed succesfully the data for message', userProfileId, messageId });
    return output;
  }
}

// => thing change / create
// [key, ] 50
