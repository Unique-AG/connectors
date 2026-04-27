import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionModule } from '../subscriptions/subscription.module';
import { DeleteInboxDataCommand } from './delete-inbox-data.command';
import { DeleteInboxDataListener } from './delete-inbox-data.listener';
import { DeleteInboxRecoveryService } from './delete-inbox-recovery.service';
import { ExecuteInboxDeletionCommand } from './execute-inbox-deletion.command';

@Module({
  imports: [
    DrizzleModule,
    AMQPModule,
    UniqueApiFeatureModule,
    DirectoriesSyncModule,
    SubscriptionModule,
  ],
  providers: [
    DeleteInboxDataCommand,
    ExecuteInboxDeletionCommand,
    DeleteInboxDataListener,
    DeleteInboxRecoveryService,
  ],
  exports: [DeleteInboxDataCommand],
})
export class DeleteInboxModule {}
