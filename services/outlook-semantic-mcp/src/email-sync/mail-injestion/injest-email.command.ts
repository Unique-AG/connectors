import { Injectable } from "@nestjs/common";
import { Span } from "nestjs-otel";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import {
  graphMessageSchema,
  GraphMessage,
  GraphMessageFields,
} from "./microsoft-graph.dtos";
import { pick } from "remeda";
import { getPossibleUniqueId } from "./get-unique-id";

@Injectable()
class InjestEmailCommand {
  constructor(private graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run({
    scopeId,
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
    scopeId: string;
  }): Promise<void> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const messageRaw = await client
      .api(`messages/${messageId}`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .select(GraphMessageFields)
      .get();

    const graphMessage = graphMessageSchema.parse(messageRaw);
    const injestionId = getPossibleUniqueId(graphMessage);
    // const metadata = pick(graphMessage, ['']);
  }

  private getMessag(graphMessage: GraphMessage) {
    // return pick(graphMessage, [''])
  }
}
