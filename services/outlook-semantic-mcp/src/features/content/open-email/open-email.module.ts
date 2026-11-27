import { Module } from '@nestjs/common';
import { GraphUtilsModule } from '~/features/graph-utils/graph-utils.module';
import { UserUtilsModule } from '~/features/user-utils/user-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { SensitivityFilter } from '../sensitivity-filter';
import { OpenEmailQuery } from './open-email.query';

@Module({
  imports: [GraphUtilsModule, MsGraphModule, UniqueApiFeatureModule, UserUtilsModule],
  providers: [OpenEmailQuery, SensitivityFilter],
  exports: [OpenEmailQuery],
})
export class OpenEmailModule {}
