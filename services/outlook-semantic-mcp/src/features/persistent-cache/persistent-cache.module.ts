import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { PersistentCacheService } from './persistent-cache.service';

@Module({
  imports: [DrizzleModule],
  providers: [PersistentCacheService],
  exports: [PersistentCacheService],
})
export class PersistentCacheModule {}
