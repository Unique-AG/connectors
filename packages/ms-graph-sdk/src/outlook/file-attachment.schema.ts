import z from 'zod/v4';

/**
 * A file (such as a text file or Word document) attached to a message or event.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/fileattachment?view=graph-rest-1.0
 */
export const FileAttachment = z.object({
  '@odata.type': z.literal('#microsoft.graph.fileAttachment'),
  name: z.string().describe('The name of the attachment.'),
  contentType: z.string().describe('The MIME type of the attachment.'),
  contentBytes: z.string().describe('The base64-encoded contents of the file.'),
});

export type FileAttachment = z.infer<typeof FileAttachment>;
