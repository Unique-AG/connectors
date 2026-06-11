import { anAttachment, aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';

const pdfBytes = Buffer.from('%PDF-1.4\n% fake pdf content for integration tests\n%%EOF\n');

/**
 * Confluence has one labeled page with one PDF attachment; Unique starts empty.
 * Expected outcome: one space scope, one HTML page file, and one PDF attachment file.
 */
export const pageWithAttachmentScenario = defineScenario({
  confluence: {
    spaces: [aSpace()],
    pages: [
      aPage({
        id: 'p1',
        title: 'Page With Attachment',
        body: '<p>See attached.</p>',
        attachments: [
          anAttachment({
            id: 'att-1',
            title: 'report.pdf',
            bytes: pdfBytes,
          }),
        ],
      }),
    ],
  },
});

export const pageWithAttachmentBytes = pdfBytes;
