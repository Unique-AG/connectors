import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { LLMModule } from '../llm/llm.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { QdrantModule } from '../qdrant/qdrant.module';
import { SemanticSearchEmailsTool } from './tools/agentic/semantic-search-emails.tool';
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
  imports: [MsGraphModule, DrizzleModule, QdrantModule, LLMModule],
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
    SemanticSearchEmailsTool,
  ],
  exports: [],
})
export class MailModule {}
