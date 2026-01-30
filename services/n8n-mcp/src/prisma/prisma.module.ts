import { Module } from '@nestjs/common';
import { PrismaProvider } from './prisma.provider';
import { PrismaService } from './prisma.service';

@Module({
  imports: [],
  providers: [PrismaProvider, PrismaService],
  exports: [PrismaProvider, PrismaService],
})
export class PrismaModule {}
