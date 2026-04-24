import { Injectable } from '@nestjs/common';
import z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

const translateIdsResponseSchema = z.object({
  value: z.array(z.object({ sourceId: z.string(), targetId: z.string() })),
});

@Injectable()
export class TranslateGraphIdsToImmutableIdsQuery {
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run(userProfileId: string, ids: string[]): Promise<Map<string, string>> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const idsMap = new Map<string, string>();
    const CHUNK_SIZE = 1000;
    for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
      const inputIds = ids.slice(i, i + CHUNK_SIZE);
      const raw = await client.api('me/translateExchangeIds').post({
        inputIds,
        sourceIdType: 'restId',
        targetIdType: 'restImmutableEntryId',
      });
      const { value } = translateIdsResponseSchema.parse(raw);
      value.forEach((item) => {
        idsMap.set(item.sourceId, item.targetId);
      });
    }
    return idsMap;
  }
}
