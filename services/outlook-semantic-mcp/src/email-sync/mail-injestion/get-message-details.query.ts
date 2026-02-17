import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GraphMessageFields, graphMessageSchema } from './dtos/microsoft-graph.dtos';

@Injectable()
export class GetMessageDetailsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run({ userProfileId, messageId }: { userProfileId: string; messageId: string }) {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const messageRaw = await client
      .api(`me/messages/${messageId}`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .select(GraphMessageFields)
      .get();

    this.logger.log(`Messaged data: ${JSON.stringify(messageRaw, null, 4)}`);

    return graphMessageSchema.parse(messageRaw);
  }
}

// => thing change / create
// [key, ] 50
