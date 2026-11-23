// Teams deep link for a chat message Graph sends without a `webUrl`. Format from
// https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/deep-link-teams
const TEAMS_WEB_ORIGIN = 'https://teams.microsoft.com';

const CHAT_CONTEXT = encodeURIComponent(JSON.stringify({ contextType: 'chat' }));

export function chatMessageWebUrl(chatId: string, messageId: string): string {
  return `${TEAMS_WEB_ORIGIN}/l/message/${encodeURIComponent(chatId)}/${encodeURIComponent(messageId)}?context=${CHAT_CONTEXT}`;
}
