import { Effect, Layer } from "effect"
import type { DelegatedAuth } from "../Auth/MsGraphAuth"
import {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage } from "../Schemas/OData"
import { PlannerPlanSchema, PlannerTaskSchema } from "../Schemas/PlannerTask"
import { PlannerService } from "./PlannerService"

const PlannerPlanPageSchema = ODataPage(PlannerPlanSchema)
const PlannerTaskPageSchema = ODataPage(PlannerTaskSchema)

export const PlannerServiceLive = Layer.effect(
  PlannerService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    const narrowToRateLimitOrNotFound = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      return new ResourceNotFoundError({ resource: "planner", id: "unknown" })
    }

    const narrowToRateLimitOrInvalidRequest = (
      error: MsGraphError,
    ): RateLimitedError | InvalidRequestError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "InvalidRequest") return error as InvalidRequestError
      return new RateLimitedError({ retryAfter: 0, resource: "planner" })
    }

    const narrowToRateLimitNotFoundOrInvalidRequest = (
      error: MsGraphError,
    ): RateLimitedError | ResourceNotFoundError | InvalidRequestError => {
      if (error._tag === "RateLimitedError") return error as RateLimitedError
      if (error._tag === "ResourceNotFound") return error as ResourceNotFoundError
      if (error._tag === "InvalidRequest") return error as InvalidRequestError
      return new RateLimitedError({ retryAfter: 0, resource: "planner" })
    }

    return PlannerService.of({
      listPlans: (groupId) =>
        Effect.mapError(
          http.get(`/groups/${groupId}/planner/plans`, PlannerPlanPageSchema),
          narrowToRateLimitOrNotFound,
        ),

      getPlan: (planId) =>
        Effect.mapError(
          http.get(`/planner/plans/${planId}`, PlannerPlanSchema),
          narrowToRateLimitOrNotFound,
        ),

      listTasks: (planId) =>
        Effect.mapError(
          http.get(`/planner/plans/${planId}/tasks`, PlannerTaskPageSchema),
          narrowToRateLimitOrNotFound,
        ),

      getTask: (taskId) =>
        Effect.mapError(
          http.get(`/planner/tasks/${taskId}`, PlannerTaskSchema),
          narrowToRateLimitOrNotFound,
        ),

      createTask: (task) =>
        Effect.mapError(
          http.post("/planner/tasks", task, PlannerTaskSchema),
          narrowToRateLimitOrInvalidRequest,
        ),

      updateTask: (taskId, etag, patch) =>
        Effect.mapError(
          http.patch(`/planner/tasks/${taskId}`, patch, PlannerTaskSchema, {
            "If-Match": etag,
          }),
          narrowToRateLimitNotFoundOrInvalidRequest,
        ),

      deleteTask: (taskId, etag) =>
        Effect.mapError(
          http.delete(`/planner/tasks/${taskId}`, { "If-Match": etag }),
          narrowToRateLimitOrNotFound,
        ),
    })
  }),
) as Layer.Layer<
  PlannerService,
  never,
  MsGraphHttpClient | DelegatedAuth
>
