import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, inArray, lt } from 'drizzle-orm';
import { typeid } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, searchCursors } from '~/db';
import { SearchCursorPayload, SearchCursorPayloadSchema } from './search-cursor.payload';

@Injectable()
export class SearchCursorRepository {
  private readonly logger = new Logger(SearchCursorRepository.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  // Returns the new cursor ids in the order of `payloads`.
  public async create(userProfileId: string, payloads: SearchCursorPayload[]): Promise<string[]> {
    if (!payloads.length) {
      return [];
    }
    const rows = payloads.map((payload) => ({
      id: typeid('search_cursor').toString(),
      userProfileId,
      payload,
    }));
    await this.db.insert(searchCursors).values(rows);
    return rows.map(({ id }) => id);
  }

  // Ids that are unknown, belong to another user, or no longer match the payload schema are
  // absent from the result.
  public async findForUser(
    userProfileId: string,
    ids: string[],
  ): Promise<Map<string, SearchCursorPayload>> {
    if (!ids.length) {
      return new Map();
    }
    const rows = await this.db
      .select({ id: searchCursors.id, payload: searchCursors.payload })
      .from(searchCursors)
      .where(and(eq(searchCursors.userProfileId, userProfileId), inArray(searchCursors.id, ids)));

    return new Map(
      rows.flatMap(({ id, payload }): [string, SearchCursorPayload][] => {
        const parsed = SearchCursorPayloadSchema.safeParse(payload);
        if (!parsed.success) {
          this.logger.warn({ msg: 'Stored search cursor failed schema validation', id });
          return [];
        }
        return [[id, parsed.data]];
      }),
    );
  }

  public async deleteCreatedBefore(date: Date): Promise<number> {
    const result = await this.db.delete(searchCursors).where(lt(searchCursors.createdAt, date));
    return result.rowCount ?? 0;
  }
}
