import assert from "node:assert";
import { type McpAuthenticatedRequest } from "@unique-ag/mcp-oauth";
import { type Context, Tool } from "@unique-ag/mcp-server-module";
import {
  Inject,
  Injectable,
  Logger,
  UnauthorizedException,
} from "@nestjs/common";
import { eq } from "drizzle-orm";
import { Span, TraceService } from "nestjs-otel";
import * as z from "zod";
import { DRIZZLE, DrizzleDatabase, subscriptions } from "~/drizzle";
import { SyncDirectoriesCommand } from "../sync-directories.command";

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class RunDirectorySyncTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
  ) {}

  @Tool({
    name: "run_directories_sync",
    title: "Run directories sync",
    description: "Run directories sync",
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: "Run directories sync",
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      "unique.app/icon": "play",
      "unique.app/system-prompt": "Starts directories in database",
    },
  })
  @Span()
  public async startKbIntegration(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId)
      throw new UnauthorizedException("User not authenticated");

    const span = this.traceService.getSpan();
    span?.setAttribute("user_profile_id", userProfileId);

    this.logger.log({ userProfileId }, "Starting directory sync");

    const subscription = await this.drizzle.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });
    assert.ok(
      subscription,
      `Missing subscription for userProfile: ${userProfileId}`,
    );

    try {
      await this.syncDirectoriesCommand.run(subscription.subscriptionId);
    } catch (error) {
      await this.logger.error(error);
      return { success: false, message: `Failed to run sync` };
    }

    return {
      success: true,
      message: `Successfully run`,
    };
  }
}
