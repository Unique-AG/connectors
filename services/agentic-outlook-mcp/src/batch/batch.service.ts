import { DiscoveredMethod, DiscoveryService } from '@golevelup/nestjs-discovery';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { TypeID } from 'typeid-js';
import { BatchDto, BatchOperation } from './batch.dto';
import { BatchProcessor, BatchProcessorOptions } from './batch-processor.decorator';

@Injectable()
export class BatchService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private readonly batchProcessors = new Map<string, Map<BatchOperation, DiscoveredMethod>>();

  public constructor(private readonly discoveryService: DiscoveryService) {}

  public async onModuleInit() {
    const methods = await this.discoveryService.providerMethodsWithMetaAtKey<BatchProcessorOptions>(
      BatchProcessor.KEY,
    );

    for (const method of methods) {
      if (this.batchProcessors.has(method.meta.table)) {
        this.batchProcessors
          .get(method.meta.table)
          ?.set(method.meta.operation, method.discoveredMethod);
      } else {
        this.batchProcessors.set(method.meta.table, new Map<BatchOperation, DiscoveredMethod>());
        this.batchProcessors
          .get(method.meta.table)
          ?.set(method.meta.operation, method.discoveredMethod);
      }
    }
  }

  public async batch(userProfileId: TypeID<'user_profile'>, body: BatchDto) {
    this.logger.log({
      msg: 'Received batched operations for user',
      userProfileId: userProfileId.toString(),
      clientId: body.clientId,
      size: body.data.length,
    });

    for (const operation of body.data) {
      this.logger.log({
        msg: 'Processing operation',
        userProfileId: userProfileId.toString(),
        table: operation.type,
        operation: operation.op,
        transactionId: operation.tx_id,
        operationId: operation.id,
      });

      const batchProcessor = this.batchProcessors.get(operation.type)?.get(operation.op);
      if (!batchProcessor) {
        this.logger.warn({
          msg: 'No batch processor found for operation',
          table: operation.type,
          operation: operation.op,
        });
        continue;
      }

      try {
        // biome-ignore lint/suspicious/noExplicitAny: The discovery module does not infer the type of the instance
        const handler = (batchProcessor.parentClass.instance as any)[batchProcessor.methodName];
        await handler.call(batchProcessor.parentClass.instance, userProfileId, operation.data);
      } catch (error) {
        this.logger.error({
          msg: 'Error processing operation',
          userProfileId: userProfileId.toString(),
          table: operation.type,
          operation: operation.op,
          transactionId: operation.tx_id,
          operationId: operation.id,
          error,
        });
      }
    }

    this.logger.log({
      msg: 'Successfully processed all operations',
      userProfileId,
      clientId: body.clientId,
    });
  }
}
