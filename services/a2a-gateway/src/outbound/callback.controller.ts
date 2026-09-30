import {
  Controller,
  Headers,
  HttpCode,
  HttpStatus,
  NotFoundException,
  Param,
  Post,
} from '@nestjs/common';
import { CallbackWakeups } from './callback-wakeups.service.js';

/** Public (no Kong JWT) receiver for remote push notifications about outbound tasks. */
@Controller('a2a/callbacks')
export class CallbackController {
  public constructor(private readonly wakeups: CallbackWakeups) {}

  @Post(':executionId')
  @HttpCode(HttpStatus.NO_CONTENT)
  public receive(
    @Param('executionId') executionId: string,
    @Headers('x-a2a-notification-token') token: string | undefined,
  ): void {
    // The body is ignored: callback state is never trusted, only the next GetTask is.
    if (!this.wakeups.verify(executionId, token)) {
      throw new NotFoundException();
    }
    this.wakeups.wake(executionId);
  }
}
