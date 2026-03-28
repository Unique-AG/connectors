import { Schema } from 'effect';
import { IdentitySetSchema } from './Common';

export const PlannerAssignmentSchema = Schema.Struct({
  assignedBy: Schema.optional(IdentitySetSchema),
  assignedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  orderHint: Schema.optional(Schema.String),
});

export type PlannerAssignment = Schema.Schema.Type<typeof PlannerAssignmentSchema>;

export const PlannerAppliedCategoriesSchema = Schema.Record(Schema.String, Schema.Boolean);

export type PlannerAppliedCategories = Schema.Schema.Type<typeof PlannerAppliedCategoriesSchema>;

export const PlannerAssignmentsSchema = Schema.Record(Schema.String, PlannerAssignmentSchema);

export type PlannerAssignments = Schema.Schema.Type<typeof PlannerAssignmentsSchema>;

export const PlannerTaskSchema = Schema.Struct({
  id: Schema.String,
  planId: Schema.String,
  bucketId: Schema.NullOr(Schema.String),
  title: Schema.String,
  orderHint: Schema.optional(Schema.String),
  percentComplete: Schema.Number,
  startDateTime: Schema.NullOr(Schema.String),
  dueDateTime: Schema.NullOr(Schema.String),
  createdDateTime: Schema.NullOr(Schema.String),
  completedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  assignments: PlannerAssignmentsSchema,
  createdBy: IdentitySetSchema,
  completedBy: Schema.optional(Schema.NullOr(IdentitySetSchema)),
  appliedCategories: PlannerAppliedCategoriesSchema,
  hasDescription: Schema.optional(Schema.Boolean),
  previewType: Schema.optional(
    Schema.NullOr(
      Schema.Union([
        Schema.Literal('automatic'),
        Schema.Literal('noPreview'),
        Schema.Literal('checklist'),
        Schema.Literal('description'),
        Schema.Literal('reference'),
      ]),
    ),
  ),
  referenceCount: Schema.optional(Schema.Number),
  checklistItemCount: Schema.optional(Schema.Number),
  activeChecklistItemCount: Schema.optional(Schema.Number),
  conversationThreadId: Schema.optional(Schema.NullOr(Schema.String)),
  priority: Schema.optional(Schema.Number),
  etag: Schema.optional(Schema.String),
});

export type PlannerTask = Schema.Schema.Type<typeof PlannerTaskSchema>;

export const PlannerContainerSchema = Schema.Struct({
  containerId: Schema.String,
  type: Schema.optional(
    Schema.Union([
      Schema.Literal('group'),
      Schema.Literal('roster'),
      Schema.Literal('driveItem'),
      Schema.Literal('project'),
      Schema.Literal('unknownFutureValue'),
    ]),
  ),
  url: Schema.optional(Schema.String),
});

export type PlannerContainer = Schema.Schema.Type<typeof PlannerContainerSchema>;

export const PlannerPlanSchema = Schema.Struct({
  id: Schema.String,
  title: Schema.String,
  owner: Schema.NullOr(Schema.String),
  createdBy: IdentitySetSchema,
  createdDateTime: Schema.NullOr(Schema.String),
  container: Schema.optional(PlannerContainerSchema),
  sharedWithContainers: Schema.optional(Schema.Array(PlannerContainerSchema)),
  etag: Schema.optional(Schema.String),
});

export type PlannerPlan = Schema.Schema.Type<typeof PlannerPlanSchema>;

export const CreatePlannerTaskPayloadSchema = Schema.Struct({
  planId: Schema.String,
  title: Schema.String,
  bucketId: Schema.optional(Schema.NullOr(Schema.String)),
  orderHint: Schema.optional(Schema.String),
  percentComplete: Schema.optional(Schema.Number),
  startDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  dueDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  assignments: Schema.optional(PlannerAssignmentsSchema),
  appliedCategories: Schema.optional(PlannerAppliedCategoriesSchema),
  priority: Schema.optional(Schema.Number),
  previewType: Schema.optional(
    Schema.NullOr(
      Schema.Union([
        Schema.Literal('automatic'),
        Schema.Literal('noPreview'),
        Schema.Literal('checklist'),
        Schema.Literal('description'),
        Schema.Literal('reference'),
      ]),
    ),
  ),
  conversationThreadId: Schema.optional(Schema.NullOr(Schema.String)),
});

export type CreatePlannerTaskPayload = Schema.Schema.Type<typeof CreatePlannerTaskPayloadSchema>;

export const PlannerTaskDetailsSchema = Schema.Struct({
  id: Schema.String,
  description: Schema.NullOr(Schema.String),
  previewType: Schema.optional(
    Schema.NullOr(
      Schema.Union([
        Schema.Literal('automatic'),
        Schema.Literal('noPreview'),
        Schema.Literal('checklist'),
        Schema.Literal('description'),
        Schema.Literal('reference'),
      ]),
    ),
  ),
  checklist: Schema.optional(
    Schema.Record(
      Schema.String,
      Schema.Struct({
        isChecked: Schema.Boolean,
        title: Schema.NullOr(Schema.String),
        orderHint: Schema.optional(Schema.String),
        lastModifiedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
        lastModifiedBy: Schema.optional(Schema.NullOr(IdentitySetSchema)),
      }),
    ),
  ),
  references: Schema.optional(
    Schema.Record(
      Schema.String,
      Schema.Struct({
        alias: Schema.optional(Schema.NullOr(Schema.String)),
        lastModifiedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
        lastModifiedBy: Schema.optional(Schema.NullOr(IdentitySetSchema)),
        previewPriority: Schema.optional(Schema.String),
        type: Schema.optional(Schema.NullOr(Schema.String)),
      }),
    ),
  ),
  etag: Schema.optional(Schema.String),
});

export type PlannerTaskDetails = Schema.Schema.Type<typeof PlannerTaskDetailsSchema>;
