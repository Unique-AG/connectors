import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { UserService } from './user.service';

@Module({
  imports: [DrizzleModule],
  providers: [UserService],
  exports: [],
})
export class UserModule {}
