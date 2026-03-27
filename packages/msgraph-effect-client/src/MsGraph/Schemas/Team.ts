import { Schema } from "effect";

export const TeamSchema = Schema.Struct({
  id: Schema.String,
  displayName: Schema.String,
  description: Schema.NullOr(Schema.String),
  internalId: Schema.optional(Schema.String),
  classification: Schema.optional(Schema.NullOr(Schema.String)),
  specialization: Schema.optional(
    Schema.NullOr(
      Schema.Literal(
        "none",
        "educationStandard",
        "educationClass",
        "educationProfessionalLearningCommunity",
        "educationStaff",
        "unknownFutureValue",
      ),
    ),
  ),
  visibility: Schema.optional(
    Schema.NullOr(Schema.Literal("private", "public", "hiddenMembership", "unknownFutureValue")),
  ),
  webUrl: Schema.optional(Schema.NullOr(Schema.String)),
  isArchived: Schema.optional(Schema.NullOr(Schema.Boolean)),
  tenantId: Schema.optional(Schema.String),
  createdDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  memberSettings: Schema.optional(
    Schema.Struct({
      allowCreateUpdateChannels: Schema.optional(Schema.Boolean),
      allowDeleteChannels: Schema.optional(Schema.Boolean),
      allowAddRemoveApps: Schema.optional(Schema.Boolean),
      allowCreateUpdateRemoveTabs: Schema.optional(Schema.Boolean),
      allowCreateUpdateRemoveConnectors: Schema.optional(Schema.Boolean),
    }),
  ),
  guestSettings: Schema.optional(
    Schema.Struct({
      allowCreateUpdateChannels: Schema.optional(Schema.Boolean),
      allowDeleteChannels: Schema.optional(Schema.Boolean),
    }),
  ),
  messagingSettings: Schema.optional(
    Schema.Struct({
      allowUserEditMessages: Schema.optional(Schema.Boolean),
      allowUserDeleteMessages: Schema.optional(Schema.Boolean),
      allowOwnerDeleteMessages: Schema.optional(Schema.Boolean),
      allowTeamMentions: Schema.optional(Schema.Boolean),
      allowChannelMentions: Schema.optional(Schema.Boolean),
    }),
  ),
  funSettings: Schema.optional(
    Schema.Struct({
      allowGiphy: Schema.optional(Schema.Boolean),
      giphyContentRating: Schema.optional(Schema.Literal("strict", "moderate", "unknownFutureValue")),
      allowStickersAndMemes: Schema.optional(Schema.Boolean),
      allowCustomMemes: Schema.optional(Schema.Boolean),
    }),
  ),
  discoverySettings: Schema.optional(
    Schema.Struct({
      showInTeamsSearchAndSuggestions: Schema.optional(Schema.Boolean),
    }),
  ),
});

export type Team = Schema.Schema.Type<typeof TeamSchema>;

export const ChannelSchema = Schema.Struct({
  id: Schema.String,
  displayName: Schema.String,
  description: Schema.NullOr(Schema.String),
  email: Schema.optional(Schema.NullOr(Schema.String)),
  webUrl: Schema.optional(Schema.String),
  createdDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  membershipType: Schema.optional(
    Schema.Literal("standard", "private", "unknownFutureValue", "shared"),
  ),
  isFavoriteByDefault: Schema.optional(Schema.NullOr(Schema.Boolean)),
  tenantId: Schema.optional(Schema.String),
  moderationSettings: Schema.optional(
    Schema.NullOr(
      Schema.Struct({
        userNewMessageRestriction: Schema.optional(
          Schema.Literal("everyone", "everyoneExceptGuests", "moderators", "unknownFutureValue"),
        ),
        replyRestriction: Schema.optional(
          Schema.Literal("everyone", "authorAndModerators", "unknownFutureValue"),
        ),
        allowNewMessageFromBots: Schema.optional(Schema.Boolean),
        allowNewMessageFromConnectors: Schema.optional(Schema.Boolean),
      }),
    ),
  ),
});

export type Channel = Schema.Schema.Type<typeof ChannelSchema>;

export const ChatMessageBodySchema = Schema.Struct({
  contentType: Schema.Literal("text", "html"),
  content: Schema.NullOr(Schema.String),
});

export const ChatMessageMentionSchema = Schema.Struct({
  id: Schema.Number,
  mentionText: Schema.String,
  mentioned: Schema.Struct({
    user: Schema.optional(
      Schema.Struct({
        id: Schema.String,
        displayName: Schema.optional(Schema.NullOr(Schema.String)),
        userIdentityType: Schema.optional(Schema.String),
      }),
    ),
    application: Schema.optional(
      Schema.Struct({
        id: Schema.String,
        displayName: Schema.optional(Schema.NullOr(Schema.String)),
        applicationIdentityType: Schema.optional(Schema.String),
      }),
    ),
    tag: Schema.optional(
      Schema.Struct({
        id: Schema.String,
        displayName: Schema.optional(Schema.NullOr(Schema.String)),
      }),
    ),
    channel: Schema.optional(
      Schema.Struct({
        id: Schema.String,
        displayName: Schema.optional(Schema.NullOr(Schema.String)),
        membershipType: Schema.optional(Schema.String),
      }),
    ),
  }),
});

export type ChatMessageMention = Schema.Schema.Type<typeof ChatMessageMentionSchema>;

export const ChatMessageAttachmentSchema = Schema.Struct({
  id: Schema.String,
  contentType: Schema.String,
  contentUrl: Schema.optional(Schema.NullOr(Schema.String)),
  content: Schema.optional(Schema.NullOr(Schema.String)),
  name: Schema.optional(Schema.NullOr(Schema.String)),
  thumbnailUrl: Schema.optional(Schema.NullOr(Schema.String)),
  teamsAppId: Schema.optional(Schema.NullOr(Schema.String)),
});

export type ChatMessageAttachment = Schema.Schema.Type<typeof ChatMessageAttachmentSchema>;

export const ChatMessageSchema = Schema.Struct({
  id: Schema.String,
  replyToId: Schema.optional(Schema.NullOr(Schema.String)),
  etag: Schema.optional(Schema.String),
  messageType: Schema.Literal(
    "message",
    "chatEvent",
    "typing",
    "unknownFutureValue",
    "systemEventMessage",
  ),
  createdDateTime: Schema.NullOr(Schema.String),
  lastModifiedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  lastEditedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  deletedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  subject: Schema.optional(Schema.NullOr(Schema.String)),
  body: ChatMessageBodySchema,
  summary: Schema.optional(Schema.NullOr(Schema.String)),
  chatId: Schema.optional(Schema.NullOr(Schema.String)),
  channelIdentity: Schema.optional(
    Schema.Struct({
      teamId: Schema.optional(Schema.String),
      channelId: Schema.optional(Schema.String),
    }),
  ),
  from: Schema.NullOr(
    Schema.Struct({
      application: Schema.optional(
        Schema.NullOr(
          Schema.Struct({
            id: Schema.String,
            displayName: Schema.optional(Schema.NullOr(Schema.String)),
          }),
        ),
      ),
      device: Schema.optional(
        Schema.NullOr(
          Schema.Struct({
            id: Schema.String,
            displayName: Schema.optional(Schema.NullOr(Schema.String)),
          }),
        ),
      ),
      user: Schema.optional(
        Schema.NullOr(
          Schema.Struct({
            id: Schema.String,
            displayName: Schema.optional(Schema.NullOr(Schema.String)),
            userIdentityType: Schema.optional(Schema.String),
            tenantId: Schema.optional(Schema.NullOr(Schema.String)),
          }),
        ),
      ),
    }),
  ),
  attachments: Schema.optional(Schema.Array(ChatMessageAttachmentSchema)),
  mentions: Schema.optional(Schema.Array(ChatMessageMentionSchema)),
  importance: Schema.Literal("normal", "high", "urgent"),
  reactions: Schema.optional(
    Schema.Array(
      Schema.Struct({
        reactionType: Schema.String,
        createdDateTime: Schema.String,
        user: Schema.Struct({
          application: Schema.optional(Schema.NullOr(Schema.Struct({ id: Schema.String }))),
          device: Schema.optional(Schema.NullOr(Schema.Struct({ id: Schema.String }))),
          user: Schema.optional(
            Schema.NullOr(
              Schema.Struct({
                id: Schema.String,
                displayName: Schema.optional(Schema.NullOr(Schema.String)),
                userIdentityType: Schema.optional(Schema.String),
              }),
            ),
          ),
        }),
      }),
    ),
  ),
  locale: Schema.optional(Schema.String),
  webUrl: Schema.optional(Schema.NullOr(Schema.String)),
  policyViolation: Schema.optional(Schema.NullOr(Schema.Struct({}))),
});

export type ChatMessage = Schema.Schema.Type<typeof ChatMessageSchema>;

export const SendChatMessagePayloadSchema = Schema.Struct({
  body: ChatMessageBodySchema,
  subject: Schema.optional(Schema.NullOr(Schema.String)),
  importance: Schema.optional(Schema.Literal("normal", "high", "urgent")),
  mentions: Schema.optional(Schema.Array(ChatMessageMentionSchema)),
  attachments: Schema.optional(Schema.Array(ChatMessageAttachmentSchema)),
});

export type SendChatMessagePayload = Schema.Schema.Type<typeof SendChatMessagePayloadSchema>;
