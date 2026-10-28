import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'paperclip',
  systemPrompt: `### When to Use \`remove_attachments_from_draft_email\`
    Use it when the user wants a file taken off a draft — including when a corrected file should replace an old one (remove the old attachment, then add the new one with \`add_attachments_to_draft_email\`).

    ### Read Before You Remove
    Open the draft with \`open_email\` first and take the file names from \`metadata.attachments\`. Pass them in \`fileNames\` exactly as listed. The user is asked to confirm in a prompt before anything is deleted; if they decline or their client cannot show the prompt, nothing is removed. Do not ask for the same confirmation in chat.

    ### Results
    When \`failed\` is non-empty, tell the user which files could not be removed and why.`,
});
