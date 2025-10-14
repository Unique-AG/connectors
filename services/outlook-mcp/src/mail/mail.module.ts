import { Module } from '@nestjs/common';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { CleanupPrompts } from './prompts/cleanup.prompts';
import { CompliancePrompts } from './prompts/compliance.prompts';
import { ComposePrompts } from './prompts/compose.prompts';
import { SearchPrompts } from './prompts/search.prompts';
import { TriagePrompts } from './prompts/triage.prompts';
import { WorkflowPrompts } from './prompts/workflow.prompts';
import { CreateDraftEmailTool } from './tools/create-draft-email.tool';
import { DeleteMailMessageTool } from './tools/delete-mail-message.tool';
import { GetMailMessageTool } from './tools/get-mail-message.tool';
import { ListMailFolderMessagesTool } from './tools/list-mail-folder-messages.tool';
import { ListMailFoldersTool } from './tools/list-mail-folders.tool';
import { ListMailsTool } from './tools/list-mails.tool';
import { MoveMailMessageTool } from './tools/move-mail-message.tool';
import { SearchEmailTool } from './tools/search-email.tool';
import { SendMailTool } from './tools/send-mail.tool';

@Module({
  imports: [MsGraphModule],
  providers: [
    ListMailsTool,
    SendMailTool,
    ListMailFoldersTool,
    ListMailFolderMessagesTool,
    GetMailMessageTool,
    CreateDraftEmailTool,
    DeleteMailMessageTool,
    MoveMailMessageTool,
    SearchEmailTool,
    // TriagePrompts,
    // ComposePrompts,
    // SearchPrompts,
    // WorkflowPrompts,
    // CompliancePrompts,
    // CleanupPrompts,
  ],
  exports: [],
})
export class MailModule {}
