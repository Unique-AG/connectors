import * as z from 'zod';

// ─── Teams ────────────────────────────────────────────────────────────────────

// NOTE: /me/joinedTeams populates only id, displayName, description, isArchived,
// and tenantId — visibility, webUrl, and createdDateTime are always returned as
// null on that endpoint (see user-list-joinedteams docs), so they are not
// modelled here. `isArchived` is the one extra populated field useful for
// disambiguating same-named teams (an archived team is read-only).
export const MsTeamSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().nullish(),
  isArchived: z.boolean().nullish(),
});

export type MsTeam = z.infer<typeof MsTeamSchema>;

// ─── Channels ─────────────────────────────────────────────────────────────────

export const MsChannelSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().nullish(),
  createdDateTime: z.string().nullish(),
  membershipType: z.string().nullish(),
});

export type MsChannel = z.infer<typeof MsChannelSchema>;

// ─── Chats ────────────────────────────────────────────────────────────────────

export const MsChatMemberSchema = z.object({
  userId: z.string().nullish(),
  displayName: z.string().nullish(),
  email: z.string().nullish(),
});

// `lastMessagePreview` is a navigation property (chatMessageInfo) only returned
// when $expanded on the list-chats operation; we keep just its timestamp.
export const MsChatSchema = z
  .object({
    id: z.string(),
    chatType: z.string(),
    topic: z.string().nullish(),
    createdDateTime: z.string().nullish(),
    lastMessagePreview: z.object({ createdDateTime: z.string().nullish() }).nullish(),
    members: z.array(MsChatMemberSchema),
  })
  .transform((chat) => ({
    id: chat.id,
    chatType: chat.chatType,
    topic: chat.topic,
    createdDateTime: chat.createdDateTime ?? null,
    lastMessageAt: chat.lastMessagePreview?.createdDateTime ?? null,
    members: chat.members,
  }));

// Modelled on what `chatmessage-get` returns, and shaped to match the fields the
// Anthropic Office MCP surfaces for the same resource. The body is passed through
// as Graph sends it — `contentType` plus raw `content` — and the structured
// metadata travels alongside, so nothing has to be rendered into placeholder text.
export const MsChatMessageSchema = z
  .object({
    id: z.string(),
    messageType: z.string().default('message'),
    subject: z.string().nullish(),
    body: z.object({
      contentType: z.string(),
      content: z.string(),
    }),
    from: z
      .object({
        user: z.object({ id: z.string().nullish(), displayName: z.string().nullish() }).nullish(),
        application: z
          .object({ id: z.string().nullish(), displayName: z.string().nullish() })
          .nullish(),
      })
      .nullish(),
    createdDateTime: z.string(),
    lastModifiedDateTime: z.string().nullish(),
    lastEditedDateTime: z.string().nullish(),
    deletedDateTime: z.string().nullish(),
    importance: z.string().nullish(),
    locale: z.string().nullish(),
    webUrl: z.string().nullish(),
    etag: z.string().nullish(),
    replyToId: z.string().nullish(),
    channelIdentity: z
      .object({ teamId: z.string().nullish(), channelId: z.string().nullish() })
      .nullish(),
    mentions: z
      .array(
        z.object({
          id: z.number().nullish(),
          mentionText: z.string().nullish(),
          mentioned: z
            .object({
              user: z
                .object({ id: z.string().nullish(), displayName: z.string().nullish() })
                .nullish(),
            })
            .nullish(),
        }),
      )
      .nullish(),
    reactions: z
      .array(
        z.object({
          reactionType: z.string().nullish(),
          createdDateTime: z.string().nullish(),
          user: z
            .object({
              user: z
                .object({ id: z.string().nullish(), displayName: z.string().nullish() })
                .nullish(),
            })
            .nullish(),
        }),
      )
      .nullish(),
    attachments: z
      .array(
        z.object({
          id: z.string(),
          name: z.string().nullish(),
          contentType: z.string().nullish(),
        }),
      )
      .nullish(),
  })
  .transform((msg) => ({
    id: msg.id,
    messageType: msg.messageType,
    subject: msg.subject ?? null,
    body: { contentType: msg.body.contentType, content: msg.body.content },
    from: msg.from?.user ?? msg.from?.application ?? null,
    createdDateTime: msg.createdDateTime,
    lastModifiedDateTime: msg.lastModifiedDateTime ?? null,
    lastEditedDateTime: msg.lastEditedDateTime ?? null,
    deletedDateTime: msg.deletedDateTime ?? null,
    importance: msg.importance ?? null,
    locale: msg.locale ?? null,
    webUrl: msg.webUrl ?? null,
    etag: msg.etag ?? null,
    replyToId: msg.replyToId ?? null,
    channelIdentity: msg.channelIdentity
      ? {
          teamId: msg.channelIdentity.teamId ?? null,
          channelId: msg.channelIdentity.channelId ?? null,
        }
      : null,
    mentions: (msg.mentions ?? []).map((m) => ({
      id: m.id ?? null,
      mentionText: m.mentionText ?? null,
      mentioned: m.mentioned?.user
        ? { id: m.mentioned.user.id ?? null, displayName: m.mentioned.user.displayName ?? null }
        : null,
    })),
    reactions: (msg.reactions ?? []).map((r) => ({
      reactionType: r.reactionType ?? null,
      createdDateTime: r.createdDateTime ?? null,
      user: r.user?.user
        ? { id: r.user.user.id ?? null, displayName: r.user.user.displayName ?? null }
        : null,
    })),
    attachments: (msg.attachments ?? []).map((a) => ({
      id: a.id,
      name: a.name ?? null,
      contentType: a.contentType ?? null,
    })),
  }));

// The message shape the tools return. Mirrors MsChatMessageSchema's output so a
// parsed Graph message can be handed straight to a caller.
export const MessageOutputSchema = z.object({
  id: z.string(),
  messageType: z.string(),
  subject: z.string().nullable(),
  body: z.object({ contentType: z.string(), content: z.string() }),
  from: z.object({ id: z.string().nullish(), displayName: z.string().nullish() }).nullable(),
  createdDateTime: z.string(),
  lastModifiedDateTime: z.string().nullable(),
  lastEditedDateTime: z.string().nullable(),
  deletedDateTime: z.string().nullable(),
  importance: z.string().nullable(),
  locale: z.string().nullable(),
  webUrl: z.string().nullable(),
  etag: z.string().nullable(),
  replyToId: z.string().nullable(),
  channelIdentity: z
    .object({ teamId: z.string().nullable(), channelId: z.string().nullable() })
    .nullable(),
  mentions: z.array(
    z.object({
      id: z.number().nullable(),
      mentionText: z.string().nullable(),
      mentioned: z
        .object({ id: z.string().nullable(), displayName: z.string().nullable() })
        .nullable(),
    }),
  ),
  reactions: z.array(
    z.object({
      reactionType: z.string().nullable(),
      createdDateTime: z.string().nullable(),
      user: z.object({ id: z.string().nullable(), displayName: z.string().nullable() }).nullable(),
    }),
  ),
  attachments: z.array(
    z.object({
      id: z.string(),
      name: z.string().nullable(),
      contentType: z.string().nullable(),
    }),
  ),
});

export type MsChatMember = z.infer<typeof MsChatMemberSchema>;
export type MsChat = z.infer<typeof MsChatSchema>;
export type MsChatMessage = z.infer<typeof MsChatMessageSchema>;

// ─── Search (Microsoft Search API: POST /search/query) ──────────────────────────

// The `resource` of a chatMessage hit. A hit is an Exchange copy of the message,
// not the Teams resource: the sender arrives as a mailbox `emailAddress` and the
// link as `webLink`. Microsoft documents `webUrl` and the Teams identity set
// instead, so both spellings are modelled. Graph omits most fields, so almost
// everything is nullish.
const MsSearchHitResourceSchema = z.object({
  id: z.string().nullish(),
  createdDateTime: z.string().nullish(),
  webUrl: z.string().nullish(),
  webLink: z.string().nullish(),
  subject: z.string().nullish(),
  importance: z.string().nullish(),
  // Present for chat messages (1:1 and group chats).
  chatId: z.string().nullish(),
  // Present for channel messages. Chat hits carry it as an empty object, so its
  // presence proves nothing — only its two ids do.
  channelIdentity: z
    .object({
      teamId: z.string().nullish(),
      channelId: z.string().nullish(),
    })
    .nullish(),
  from: z
    .object({
      emailAddress: z
        .object({ name: z.string().nullish(), address: z.string().nullish() })
        .nullish(),
      user: z.object({ id: z.string().nullish(), displayName: z.string().nullish() }).nullish(),
      application: z.object({ displayName: z.string().nullish() }).nullish(),
    })
    .nullish(),
});

const MsSearchHitSchema = z.object({
  hitId: z.string().nullish(),
  rank: z.number().nullish(),
  summary: z.string().nullish(),
  resource: MsSearchHitResourceSchema.nullish(),
});

const MsSearchHitsContainerSchema = z.object({
  hits: z.array(MsSearchHitSchema).nullish(),
  total: z.number().nullish(),
  moreResultsAvailable: z.boolean().nullish(),
});

export const MsSearchResponseSchema = z.object({
  value: z
    .array(
      z.object({
        hitsContainers: z.array(MsSearchHitsContainerSchema).nullish(),
      }),
    )
    .nullish(),
});

export type MsSearchHit = z.infer<typeof MsSearchHitSchema>;
export type MsSearchResponse = z.infer<typeof MsSearchResponseSchema>;
