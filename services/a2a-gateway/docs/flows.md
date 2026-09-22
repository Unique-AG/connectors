# Flows

## Inbound: `SendStreamingMessage` on a published space

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    participant C as A2A client
    participant GW as a2a-gateway
    participant DB as gateway DB
    participant Chat as node-chat

    C->>GW: SendStreamingMessage(contextId?, parts) · Bearer
    GW->>GW: verify token, resolve publication (enabled?)
    GW->>Chat: space use access · x-user-id/x-company-id
    Chat-->>GW: ok
    GW->>DB: upsert context (chatId or null), check no active task
    GW->>Chat: upload file parts (contentUpsertByChat) [if any]
    GW->>Chat: messageCreate(assistantId, chatId?, text, selectedUploadedFileIds)
    Chat-->>GW: userMessage {id, chatId}
    GW->>DB: create task SUBMITTED, context.chatId
    GW-->>C: SSE: Task
    GW->>Chat: run events (see D-07)
    loop events
        Chat-->>GW: stream chunk / update / elicitation pending / finished
        GW->>DB: update task snapshot
        GW-->>C: SSE: TaskStatusUpdateEvent / TaskArtifactUpdateEvent
    end
    GW-->>C: SSE: final status (COMPLETED | INPUT_REQUIRED | AUTH_REQUIRED | FAILED)
```

Non-streaming `SendMessage`: same, but the gateway waits (bounded by `SYNC_WAIT_MAX`) and returns the `Task`; if the run is still active the task is returned in `WORKING` and the client polls `GetTask`/`SubscribeToTask`.

## Inbound: multi-turn with elicitation

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    participant C as A2A client
    participant GW as a2a-gateway
    participant Chat as node-chat

    Chat-->>GW: elicitation pending (FORM schema | URL)
    GW-->>C: status INPUT_REQUIRED (data part = schema) | AUTH_REQUIRED (url)
    C->>GW: SendMessage(taskId, contextId, data part = answer) | (taskId, text "done")
    GW->>Chat: elicitationRespond(id, ACCEPTED, content) · same user
    Chat-->>GW: run continues
    GW-->>C: status WORKING → COMPLETED + artifacts
```

Declined or expired elicitation → `FAILED` with `ErrorInfo.reason = ELICITATION_DECLINED | ELICITATION_EXPIRED`. Follow-ups after a terminal task start a **new** task in the same context.

## Inbound: `CancelTask`

`CancelTask(taskId)` → authorise `(companyId, userId)` → `messageStopStreaming(chatId, assistantMessageId)` → task `CANCELED` when core confirms `stoppedStreamingAt`; if the task is already terminal → `TASK_NOT_CANCELABLE`.

## Outbound: direct chat in an A2A External Agent space

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    actor U as User
    participant Chat as node-chat
    participant GW as a2a-gateway
    participant R as Remote agent

    U->>Chat: send message
    Chat->>Chat: create user + assistant shell message, authz, gates
    Chat->>GW: POST /internal/executions {connectionId, chatId, messages, parts} · user headers
    GW->>GW: load connection + negotiated caps, resolve remote contextId for chatId
    GW-->>Chat: 202 {executionId}
    alt streaming supported
        GW->>R: SendStreamingMessage(contextId?, parts) · connection credential
        R-->>GW: SSE task events
    else
        GW->>R: SendMessage
        GW->>GW: worker polls GetTask until terminal
    end
    loop per event
        GW->>Chat: message update (text so far) · user headers
    end
    alt INPUT_REQUIRED / AUTH_REQUIRED
        GW->>Chat: elicitationCreate(FORM schema | URL) + message text
        U->>Chat: answers elicitation
        Chat-->>GW: (D-08) elicitation ACCEPTED
        GW->>R: SendMessage(taskId, answer)
    end
    R-->>GW: COMPLETED + artifacts
    GW->>Chat: download remote files → upload to chat; final message update (text, references, files), completedAt
```

`U` stops the message → core → `POST /internal/executions/{id}/cancel` → `CancelTask` on remote → message marked stopped.

## Outbound: sub-agent call from a native space

Unchanged for core: the Conduct `SubAgentTool` sends a message with `correlation` to the external space via the existing space-message path. `node-chat` sees `executionProvider = A2A` and dispatches to the gateway exactly like direct chat; the sub-agent tool keeps polling the latest message. Elicitations bubble up through existing correlation handling; the gateway never approves.

## Push notifications (inbound)

`CreateTaskPushNotificationConfig(taskId, url, authentication)` → egress guard → stored encrypted. On every status change the worker POSTs the `Task` (status only, no artifacts) with the configured `Authorization`; retries with backoff, disabled after `PUSH_MAX_FAILURES`.

## Recovery

- Gateway restart during inbound task: task stays `WORKING`; `GetTask`/`SubscribeToTask` re-derive state from core message state (poll) — no second `messageCreate` (unique `user_message_id`).
- Gateway restart during outbound execution: worker resumes `outbound.poll` for non-terminal executions; if the remote lacks `GetTask` continuity the execution fails with a clear message in the chat.
- Core unreachable: inbound requests fail with `-32603` + `ErrorInfo.reason = UPSTREAM_UNAVAILABLE`; outbound updates are retried, then the execution fails.
