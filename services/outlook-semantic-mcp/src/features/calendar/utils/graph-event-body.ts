const TEAMS_UNDERSCORE_RULE = '____________________';
const TEAMS_EMAIL_TEXT_CLASS = /class=["']me-email-text["']/i;
const BODY_OPEN_TAG = /<body[^>]*>/i;

/**
 * Graph stores a Teams meeting body as an HTML document:
 *
 *   <html><head>…</head><body>
 *     {user agenda HTML, passed through unchanged}
 *     <div>…gray underscore rule…</div>
 *     <div class="me-email-text">
 *       <a class="me-email-headline" href="https://teams.microsoft.com/l/meetup-join/…">
 *         Join Microsoft Teams Meeting
 *       </a>
 *       dial-in, conference ID, Local numbers | Reset PIN | Learn more | Meeting options
 *     </div>
 *     <div>…gray underscore rule…</div>
 *   </body></html>
 *
 * event-update requires that Microsoft-inserted HTML stay in the body; dropping it
 * disables the online meeting. https://learn.microsoft.com/en-us/graph/api/event-update
 *
 * The agenda string is the agent's HTML. Do not convert, escape, or rewrite it —
 * only place it in front of Microsoft's insert when that insert already exists.
 */
export function graphEventBody(
  html: string,
  existingHtml?: string,
): { contentType: 'HTML'; content: string } {
  return {
    contentType: 'HTML',
    content: spliceUserHtmlIntoEventBody(html, existingHtml),
  };
}

export function spliceUserHtmlIntoEventBody(
  userHtml: string,
  existingHtml: string | undefined,
): string {
  if (existingHtml === undefined || existingHtml.length === 0) {
    return userHtml;
  }
  const insertStart = microsoftInsertedHtmlStart(existingHtml);
  if (insertStart === undefined) {
    return userHtml;
  }
  const bodyOpen = BODY_OPEN_TAG.exec(existingHtml);
  if (bodyOpen !== null && bodyOpen.index + bodyOpen[0].length <= insertStart) {
    return `${existingHtml.slice(0, bodyOpen.index + bodyOpen[0].length)}${userHtml}${existingHtml.slice(insertStart)}`;
  }
  return `${userHtml}${existingHtml.slice(insertStart)}`;
}

function microsoftInsertedHtmlStart(existingHtml: string): number | undefined {
  const classMatch = TEAMS_EMAIL_TEXT_CLASS.exec(existingHtml);
  if (classMatch === null) {
    return undefined;
  }
  const meetingDiv = existingHtml.lastIndexOf('<div', classMatch.index);
  if (meetingDiv < 0) {
    return undefined;
  }
  const before = existingHtml.slice(0, meetingDiv);
  const previousDiv = before.lastIndexOf('<div');
  if (previousDiv >= 0 && before.slice(previousDiv).includes(TEAMS_UNDERSCORE_RULE)) {
    return previousDiv;
  }
  return meetingDiv;
}
