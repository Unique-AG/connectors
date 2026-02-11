import { Injectable, NotImplementedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';

@Injectable()
export class InjestEmailCommand {
  @Span()
  public async run(email: {
    subject: string;
    key: string;
    metadata: Record<string, string>;
    content: ReadableStream<Uint8Array<ArrayBuffer>>;
  }): Promise<void> {
    throw new NotImplementedException(`InjestEmailCommand.run not implemented`);
  }
}
