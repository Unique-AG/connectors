import { ClientFactory, JsonRpcTransportFactory } from '@a2a-js/sdk/client';
import { Injectable } from '@nestjs/common';

@Injectable()
export class A2aSdkService {
  public readonly clientFactory = new ClientFactory({
    transports: [new JsonRpcTransportFactory()],
    preferredTransports: ['JSONRPC'],
  });
}
