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
    messageType: z.string().default('message'),
    deletedDateTime: z.string().nullish(),
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
    deletedDateTime: msg.deletedDateTime ?? null,
  }));

export type MsChatMember = z.infer<typeof MsChatMemberSchema>;
export type MsChat = z.infer<typeof MsChatSchema>;
export type MsChatMessage = z.infer<typeof MsChatMessageSchema>;

// ─── Search (Microsoft Search API: POST /search/query) ──────────────────────────

// The `resource` of a chatMessage hit. Graph omits most fields depending on the
// message kind (1:1 chat vs channel), so almost everything is nullish.
//
// A search hit is an Exchange/substrate projection of the chatMessage, not the
// Teams-native resource: the sender arrives as a mailbox `emailAddress` and the
// link arrives as an Outlook Web `webLink`, even though Microsoft's retrievable
// property list for chatMessage search names `webUrl` and the Teams identity
// set. Both spellings are modelled so the projection is understood whichever
// one the tenant returns.
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
