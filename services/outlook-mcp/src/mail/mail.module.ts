import { Module } from '@nestjs/common';
import { MsGraphModule } from '../msgraph/msgraph.module';
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
  ],
  exports: [],
})
export class MailModule {}
