import { Module } from '@nestjs/common';
import { Agent, Dispatcher, interceptors } from 'undici';

export abstract class HttpClientService extends Dispatcher {}

@Module({
  providers: [
    {
      provide: HttpClientService,
      useFactory: (): Dispatcher => {
        return new Agent().compose([interceptors.retry(), interceptors.redirect()]);
      },
    },
  ],
  exports: [HttpClientService],
})
export class HttpClientModule {}
