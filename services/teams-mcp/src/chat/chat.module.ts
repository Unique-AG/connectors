import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { ChannelService } from './channel.service';
import { ChatService } from './chat.service';
import {
  GetChatMessagesTool,
  ListChannelsTool,
  ListChatsTool,
  ListTeamsTool,
  SendChannelMessageTool,
  SendChatMessageTool,
} from './tools';

@Module({
  imports: [MsGraphModule],
  providers: [
    // Services
    ChannelService,
    ChatService,
    // Tools
    ListTeamsTool,
    ListChannelsTool,
    ListChatsTool,
    GetChatMessagesTool,
    SendChannelMessageTool,
    SendChatMessageTool,
  ],
})
export class ChatModule {}
