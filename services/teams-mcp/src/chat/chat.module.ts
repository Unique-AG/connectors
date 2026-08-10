import { Module, type Type } from '@nestjs/common';
import { isChatEnabled } from '~/capabilities';
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

export function shouldRegisterChatModule(): boolean {
  return isChatEnabled();
}

/**
 * Optional Teams chat/channel messaging surface (chat & channel tools). Registered
 * only when CHAT_INTEGRATION is not `disabled` (default enabled) so ingestion-only
 * deployments never expose chat tools nor request the messaging Graph scopes.
 */
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

export function registerChatModule(): Type<ChatModule>[] {
  if (!shouldRegisterChatModule()) {
    return [];
  }

  return [ChatModule];
}
