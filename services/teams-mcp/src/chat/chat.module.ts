import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { ChannelService } from './channel.service';
import { ChatService } from './chat.service';
import { SearchService } from './search.service';
import {
  GetChannelMessagesTool,
  GetChatMessagesTool,
  ListChannelsTool,
  ListChatsTool,
  ListTeamsTool,
  SearchMessagesTool,
  SendChannelMessageTool,
  SendChatMessageTool,
} from './tools';

@Module({
  imports: [MsGraphModule],
  providers: [
    // Services
    ChannelService,
    ChatService,
    SearchService,
    // Tools
    ListTeamsTool,
    ListChannelsTool,
    ListChatsTool,
    GetChatMessagesTool,
    GetChannelMessagesTool,
    SearchMessagesTool,
    SendChannelMessageTool,
    SendChatMessageTool,
  ],
})
export class ChatModule {}
