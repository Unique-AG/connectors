export const serverInstructions = `
## Tool Selection Guidelines for Teams MCP

### Identifiers
- \`chatId\`, \`teamId\`, \`channelId\` and message \`id\` / \`messageId\` are internal identifiers. Pass them between tools unchanged, but never show them to the user.
- When listing chats, teams or channels, show only human-readable fields: a chat's topic or member names, its type and the date of its last message, plus its last message preview only when two chats would otherwise read the same; a team's or channel's display name. Number the entries so the user can pick one by number, and map that number back to the identifier yourself.
`;
