import { WorkflowRuntime } from "@dapr/dapr";
import { Injectable, OnModuleInit } from "@nestjs/common";
import { ingestWorkflow } from "./ingest.workflow";

@Injectable()
export class WorkflowRegistrationService implements OnModuleInit {
  public constructor(private readonly runtime: WorkflowRuntime) {}

  public async onModuleInit() {
    this.runtime.registerWorkflow(ingestWorkflow);
  }
}