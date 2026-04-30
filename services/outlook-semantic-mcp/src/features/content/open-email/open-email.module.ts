import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { OpenEmailQuery } from './open-email.query';

@Module({
  imports: [MsGraphModule, UniqueApiFeatureModule],
  providers: [OpenEmailQuery],
  exports: [OpenEmailQuery],
})
export class OpenEmailModule {}
