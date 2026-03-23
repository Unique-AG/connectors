import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { ChannelService } from './channel.service';
import { ChatService } from './chat.service';
import {
  GetChannelMessagesTool,
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
    GetChannelMessagesTool,
    SendChannelMessageTool,
    SendChatMessageTool,
  ],
})
export class ChatModule {}
