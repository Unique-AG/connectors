import { Injectable } from "@nestjs/common";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import {
  GraphMessageFields,
  graphMessageSchema,
} from "./dtos/microsoft-graph.dtos";

@Injectable()
export class GetMessageDetailsQuery {
  constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run({
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
  }) {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const messageRaw = await client
      .api(`messages/${messageId}`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .select(GraphMessageFields)
      .get();

    return graphMessageSchema.parse(messageRaw);
  }
}
