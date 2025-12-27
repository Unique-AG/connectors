import z from 'zod/v4';
import { typeid } from '~/utils/zod';

export const UserUpsertEvent = z.object({
  type: z.literal('user.upsert'),
  id: typeid('user_profile'),
});
export type UserUpsertEvent = z.infer<typeof UserUpsertEvent>;
