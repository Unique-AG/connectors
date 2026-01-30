import { Module } from '@nestjs/common';
import { N8nApiModule } from '../../n8n-api/n8n-api.module';
import { GetExecutionTool } from './get-execution.tool';
import { ListExecutionsTool } from './list-executions.tool';
import { RetryExecutionTool } from './retry-execution.tool';

@Module({
  imports: [N8nApiModule],
  providers: [ListExecutionsTool, GetExecutionTool, RetryExecutionTool],
})
export class ExecutionsModule {}
