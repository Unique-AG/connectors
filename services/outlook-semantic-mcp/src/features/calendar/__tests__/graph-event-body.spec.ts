import { describe, expect, it } from 'vitest';
import { graphEventBody, spliceUserHtmlIntoEventBody } from '../utils/graph-event-body';

const TEAMS_INSERT = `<div style="width:100%; height:20px"><span style="white-space:nowrap; color:gray; opacity:.36">________________________________________________________________________________</span>
</div>
<div class="me-email-text"><a class="me-email-headline" href="https://teams.microsoft.com/l/meetup-join/abc">Join Microsoft Teams Meeting</a></div>
<div style="width:100%; height:20px"><span style="white-space:nowrap; color:gray; opacity:.36">________________________________________________________________________________</span>
</div>`;

const AGENDA_HTML = '<p>Hello <strong>world</strong></p>';

describe('spliceUserHtmlIntoEventBody', () => {
  it('returns the agent HTML unchanged when there is no Teams insert', () => {
    expect(spliceUserHtmlIntoEventBody(AGENDA_HTML, '<html><body><p>Old</p></body></html>')).toBe(
      AGENDA_HTML,
    );
    expect(spliceUserHtmlIntoEventBody(AGENDA_HTML, undefined)).toBe(AGENDA_HTML);
  });

  it('replaces only the user region inside the existing HTML document', () => {
    const existing = `<html><head><meta charset="utf-8"></head><body>\r\n<p>Old agenda</p>\r\n${TEAMS_INSERT}</body>\r\n</html>\r\n`;

    expect(spliceUserHtmlIntoEventBody(AGENDA_HTML, existing)).toBe(
      `<html><head><meta charset="utf-8"></head><body>${AGENDA_HTML}${TEAMS_INSERT}</body>\r\n</html>\r\n`,
    );
  });
});

describe('graphEventBody', () => {
  it('sends the agent HTML through unchanged', () => {
    expect(graphEventBody(AGENDA_HTML)).toEqual({
      contentType: 'HTML',
      content: AGENDA_HTML,
    });
    expect(graphEventBody('Hello **world**')).toEqual({
      contentType: 'HTML',
      content: 'Hello **world**',
    });
  });

  it('keeps the Microsoft Teams HTML and puts the agent HTML in the same document', () => {
    const existing = `<html><body><p>Old</p>${TEAMS_INSERT}</body></html>`;

    expect(graphEventBody(AGENDA_HTML, existing)).toEqual({
      contentType: 'HTML',
      content: `<html><body>${AGENDA_HTML}${TEAMS_INSERT}</body></html>`,
    });
  });
});
