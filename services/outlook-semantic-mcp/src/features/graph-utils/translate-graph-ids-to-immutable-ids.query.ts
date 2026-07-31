import { createSmeared, smearEmail } from '@unique-ag/utils';
import { Injectable, Logger } from '@nestjs/common';
import { filter, isNonNullish, pipe, unique } from 'remeda';
import z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

const translateIdsResponseSchema = z.object({
  value: z.array(z.object({ sourceId: z.string(), targetId: z.string().optional().nullish() })),
});

type IdValue = string | null | undefined;

@Injectable()
export class TranslateGraphIdsToImmutableIdsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run({
    userProfileId,
    ids,
    ownerEmail,
  }: {
    userProfileId: string;
    ids: IdValue[];
    ownerEmail?: string;
  }): Promise<Map<string, string>> {
    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);
      const idsMap = new Map<string, string>();
      const idsList = unique(pipe(ids, filter(isNonNullish)));
      const endpoint = ownerEmail
        ? `users/${ownerEmail}/translateExchangeIds`
        : 'me/translateExchangeIds';
      const CHUNK_SIZE = 1000;
      for (let i = 0; i < idsList.length; i += CHUNK_SIZE) {
        const inputIds = idsList.slice(i, i + CHUNK_SIZE);
        const raw = await client.api(endpoint).post({
          inputIds,
          sourceIdType: 'restId',
          targetIdType: 'restImmutableEntryId',
        });
        const { value } = translateIdsResponseSchema.parse(raw);
        value.forEach((item) => {
          if (item.targetId) {
            idsMap.set(item.sourceId, item.targetId);
          }
        });
      }
      return idsMap;
    } catch (err) {
      this.logger.warn({
        err,
        msg: `Failed to translate exchange ids`,
        userProfileId,
        ...(ownerEmail ? { ownerEmail: smearEmail(createSmeared(ownerEmail)) } : {}),
      });
      return new Map<string, string>();
    }
  }
}
