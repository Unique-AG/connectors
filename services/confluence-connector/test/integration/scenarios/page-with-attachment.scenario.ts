import { defineScenario } from '../scenario/scenario.builder';

const pdfBytes = Buffer.from('%PDF-1.4\n% fake pdf content for integration tests\n%%EOF\n');

/**
 * Confluence has one labeled page with one PDF attachment; Unique starts empty.
 * Expected outcome: one space scope, one HTML page file, and one PDF attachment file.
 */
export const pageWithAttachmentScenario = defineScenario({
  confluence: {
    spaces: [{ id: 'space-1', key: 'SP', name: 'Space One' }],
    pages: [
      {
        id: 'p1',
        spaceKey: 'SP',
        title: 'Page With Attachment',
        body: '<p>See attached.</p>',
        labels: ['ai-ingest'],
        versionWhen: '2026-05-01T10:00:00.000Z',
        attachments: [
          {
            id: 'att-1',
            title: 'report.pdf',
            mediaType: 'application/pdf',
            bytes: pdfBytes,
            versionWhen: '2026-05-01T10:00:00.000Z',
          },
        ],
      },
    ],
  },
});

export const pageWithAttachmentBytes = pdfBytes;
