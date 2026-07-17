import { Module } from '@nestjs/common';
import { DemoRepository } from './demo.repository';

@Module({
  providers: [DemoRepository],
  exports: [DemoRepository],
})
export class DataModule {}
