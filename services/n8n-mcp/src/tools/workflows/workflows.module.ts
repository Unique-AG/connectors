import { Module } from '@nestjs/common';
import { N8nApiModule } from '../../n8n-api/n8n-api.module';
import { CreateWorkflowTool } from './create-workflow.tool';
import { ExecuteWorkflowTool } from './execute-workflow.tool';
import { GetWorkflowTool } from './get-workflow.tool';
import { ListWorkflowsTool } from './list-workflows.tool';
import { UpdateWorkflowTool } from './update-workflow.tool';

@Module({
  imports: [N8nApiModule],
  providers: [
    ListWorkflowsTool,
    GetWorkflowTool,
    CreateWorkflowTool,
    UpdateWorkflowTool,
    ExecuteWorkflowTool,
  ],
})
export class WorkflowsModule {}
