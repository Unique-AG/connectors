import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { UniqueService } from './unique.service';

@Module({
  imports: [DrizzleModule],
  providers: [UniqueService],
  exports: [UniqueService],
})
export class UniqueModule {}
