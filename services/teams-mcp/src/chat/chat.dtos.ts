import * as z from 'zod';

// ─── Teams ────────────────────────────────────────────────────────────────────

export const MsTeamSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});

export type MsTeam = z.infer<typeof MsTeamSchema>;

// ─── Channels ─────────────────────────────────────────────────────────────────

export const MsChannelSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});

export type MsChannel = z.infer<typeof MsChannelSchema>;

// ─── Chats ────────────────────────────────────────────────────────────────────

export const MsChatMemberSchema = z.object({
  displayName: z.string().optional(),
  email: z.string().optional(),
});

export const MsChatSchema = z.object({
  id: z.string(),
  chatType: z.string(),
  topic: z.string().optional(),
  members: z.array(MsChatMemberSchema),
});

export const MsChatMessageSchema = z
  .object({
    id: z.string(),
    createdDateTime: z.string(),
    from: z
      .object({
        user: z.object({ displayName: z.string().optional() }).nullish(),
        application: z.object({ displayName: z.string().optional() }).nullish(),
      })
      .nullish(),
    body: z.object({
      contentType: z.string(),
      content: z.string(),
    }),
    attachments: z
      .array(
        z.object({
          id: z.string(),
          name: z.string().nullish(),
        }),
      )
      .nullish(),
    messageType: z.string().optional(),
  })
  .transform((msg) => ({
    id: msg.id,
    createdDateTime: msg.createdDateTime,
    senderDisplayName:
      msg.from?.user?.displayName ?? msg.from?.application?.displayName ?? undefined,
    content: msg.body.content,
    contentType: msg.body.contentType,
    attachments: (msg.attachments ?? []).map((a) => ({ id: a.id, name: a.name ?? null })),
    messageType: msg.messageType,
  }));

export type MsChatMember = z.infer<typeof MsChatMemberSchema>;
export type MsChat = z.infer<typeof MsChatSchema>;
export type MsChatMessage = z.infer<typeof MsChatMessageSchema>;
