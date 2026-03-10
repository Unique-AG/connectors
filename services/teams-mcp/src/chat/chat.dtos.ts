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

export const MsChatMessageSchema = z.object({
  id: z.string(),
  createdDateTime: z.string(),
  senderDisplayName: z.string().optional(),
  content: z.string(),
  contentType: z.string(),
});

export type MsChatMember = z.infer<typeof MsChatMemberSchema>;
export type MsChat = z.infer<typeof MsChatSchema>;
export type MsChatMessage = z.infer<typeof MsChatMessageSchema>;
