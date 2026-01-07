# Flows

## User Connection Flow

Everything starts when a user connects to the MCP server. This triggers OAuth authentication and sets up the subscription for receiving meeting notifications.

```mermaid
flowchart LR
    subgraph Connection["User Connects to MCP Server"]
        Connect["User opens MCP client"]
        MCPEndpoint["GET /mcp"]
    end

    subgraph Auth["OAuth Authentication"]
        Redirect["Redirect to Microsoft"]
        Consent["User grants permissions"]
        Callback["Callback with auth code"]
        Exchange["Exchange for tokens"]
        Store["Store encrypted tokens"]
    end

    subgraph Setup["Subscription Setup"]
        UserUpsert["Emit UserUpsertEvent"]
        CreateSub["Create Graph subscription"]
        StoreSub["Store subscription record"]
    end

    subgraph Ready["Ready for Notifications"]
        Active["Subscription Active"]
        Listen["Listening for transcripts"]
    end

    Connect --> MCPEndpoint
    MCPEndpoint --> Redirect
    Redirect --> Consent
    Consent --> Callback
    Callback --> Exchange
    Exchange --> Store
    Store --> UserUpsert
    UserUpsert --> CreateSub
    CreateSub --> StoreSub
    StoreSub --> Active
    Active --> Listen
```

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant MCPClient as MCP Client
    participant TeamsMCP as Teams MCP Server
    participant EntraID as Microsoft Entra ID
    participant MSGraph as Microsoft Graph API
    participant DB as PostgreSQL

    User->>MCPClient: Connect to MCP server
    MCPClient->>TeamsMCP: GET /mcp
    TeamsMCP->>MCPClient: Redirect to Microsoft login
    MCPClient->>EntraID: OAuth authorization request
    EntraID->>User: Show consent screen
    User->>EntraID: Grant permissions
    EntraID->>MCPClient: Redirect with auth code
    MCPClient->>TeamsMCP: GET /auth/callback?code=...
    TeamsMCP->>EntraID: Exchange code for tokens
    EntraID->>TeamsMCP: Access + Refresh tokens
    TeamsMCP->>DB: Store encrypted tokens

    Note over TeamsMCP: Emit UserUpsertEvent
    TeamsMCP->>MSGraph: POST /subscriptions
    MSGraph->>TeamsMCP: Subscription created (ID, expiry)
    TeamsMCP->>DB: Store subscription record
    TeamsMCP->>MCPClient: Connection complete

    Note over TeamsMCP: Now listening for meeting transcripts
```

**OAuth Scopes Required:** See [Microsoft Graph Permissions](./permissions.md) for detailed justification.

## Subscription Lifecycle

Subscriptions are **renewed** (not recreated) before they expire. If renewal fails for any reason, the subscription is deleted and the user must reconnect to the MCP server to re-authenticate.

```mermaid
stateDiagram-v2
    [*] --> Creating: User connects to MCP

    Creating --> Active: Subscription created
    Active --> Renewing: Lifecycle notification<br/>(before expiry)
    Renewing --> Active: Renewal successful
    Renewing --> Deleted: Renewal failed
    Active --> Deleted: User disconnects
    Deleted --> [*]: User must reconnect

    note right of Creating
        Creates subscription for:
        users/{id}/onlineMeetings/getAllTranscripts
    end note

    note right of Deleted
        User must reconnect to
        MCP server and re-authenticate
    end note
```

```mermaid
sequenceDiagram
    autonumber
    participant TeamsMCP as Teams MCP Server
    participant RabbitMQ
    participant MSGraph as Microsoft Graph API
    participant DB as PostgreSQL

    Note over TeamsMCP: User connected, subscription active

    rect rgb(200, 230, 200)
        Note over MSGraph: Before expiry - Lifecycle notification
        MSGraph->>TeamsMCP: POST /transcript/lifecycle
        TeamsMCP->>RabbitMQ: Enqueue reauthorization event
        RabbitMQ->>TeamsMCP: Process reauthorization
        TeamsMCP->>MSGraph: PATCH /subscriptions/{id} (renew)
        MSGraph->>TeamsMCP: Subscription renewed
        TeamsMCP->>DB: Update expiration time
    end

    rect rgb(255, 200, 200)
        Note over TeamsMCP: If renewal fails
        TeamsMCP->>MSGraph: DELETE /subscriptions/{id}
        TeamsMCP->>DB: Delete subscription record
        Note over TeamsMCP: User must reconnect to MCP server
    end
```

**Subscription Scheduling:**
- Subscriptions are set to expire at a configured UTC hour (default: 3 AM)
- This batches all renewals to a single time window
- Daily renewal ensures token validity is checked consistently
- Minimum 2-hour subscription lifetime required for lifecycle notifications
- **If renewal fails**: Subscription is deleted and user must reconnect to MCP server

## Transcript Processing Flow

When a meeting transcript becomes available, Microsoft Graph sends a webhook notification. The recording is fetched **only if the user has recording permissions**.

```mermaid
sequenceDiagram
    autonumber
    participant MSGraph as Microsoft Graph API
    participant Controller as Webhook Controller
    participant RabbitMQ
    participant Service as Transcript Created Service
    participant Unique as Unique Platform

    Note over MSGraph: Meeting transcript available
    MSGraph->>Controller: POST /transcript/notification
    Controller->>Controller: Validate clientState
    Controller->>RabbitMQ: Enqueue change notification

    RabbitMQ->>Service: Process transcript.created event

    par Fetch meeting data
        Service->>MSGraph: GET /onlineMeetings/{id}
        MSGraph->>Service: Meeting details + participants
    and Fetch transcript
        Service->>MSGraph: GET /transcripts/{id}
        MSGraph->>Service: Transcript metadata
        Service->>MSGraph: GET /transcripts/{id}/content
        MSGraph->>Service: VTT content stream
    end

    opt Recording permissions available
        Service->>MSGraph: GET /recordings?filter=correlationId
        MSGraph->>Service: Recording metadata + stream
    end

    Service->>Unique: Resolve participants to user IDs
    Service->>Unique: Create scope (folder)
    Service->>Unique: Set access permissions
    Service->>Unique: Upload transcript (VTT)

    opt Recording was fetched
        Service->>Unique: Upload recording (MP4)
    end
```

```mermaid
flowchart TB
    subgraph Input["Microsoft Graph Webhook"]
        Notification["Change Notification"]
    end

    subgraph Validation["Validation"]
        ClientState["clientState Validation"]
    end

    subgraph Queue["Message Queue"]
        Exchange{{"teams-mcp.exchange"}}
        DLX{{"Dead Letter Exchange"}}
    end

    subgraph Processing["Transcript Processing"]
        FetchMeeting["Fetch Meeting Details"]
        FetchTranscript["Fetch Transcript Content"]
        CheckPerms{"Recording<br/>permissions?"}
        FetchRecording["Fetch Recording"]
        SkipRecording["Skip Recording"]
        ResolveUsers["Resolve Participants"]
    end

    subgraph Ingestion["Unique Ingestion"]
        CreateScope["Create Scope"]
        SetAccess["Set Permissions"]
        UploadVTT["Upload Transcript"]
        CheckRecording{"Recording<br/>available?"}
        UploadMP4["Upload Recording"]
        Done["Done"]
    end

    Notification --> ClientState
    ClientState -->|Valid| Exchange
    ClientState -->|Invalid| Reject["Reject Request"]

    Exchange --> FetchMeeting
    Exchange -.->|Failed| DLX

    FetchMeeting --> FetchTranscript
    FetchTranscript --> CheckPerms
    CheckPerms -->|Yes| FetchRecording
    CheckPerms -->|No| SkipRecording
    FetchRecording --> ResolveUsers
    SkipRecording --> ResolveUsers

    ResolveUsers --> CreateScope
    CreateScope --> SetAccess
    SetAccess --> UploadVTT
    UploadVTT --> CheckRecording
    CheckRecording -->|Yes| UploadMP4
    CheckRecording -->|No| Done
    UploadMP4 --> Done
```

**Webhook Validation:**
- Microsoft Graph sends a `clientState` value with each notification
- The server validates this matches the secret configured during subscription creation
- Invalid `clientState` results in request rejection

**Recording Permissions:**
- Recording fetch requires `OnlineMeetingRecording.Read.All` scope
- If the user hasn't granted this permission, only the transcript is captured
- Recording availability is checked before attempting upload

**Access Control:**
- Meeting organizer receives **write + read** access
- Meeting participants receive **read** access
- Users are resolved by email or username in Unique platform

## Related Documentation

- [Architecture](./architecture.md) - System components and infrastructure
- [Token and Authentication](./token-auth-flows.md) - Token types, validation, refresh flows
- [Microsoft Graph Permissions](./permissions.md) - Required scopes and least-privilege justification
- [Why RabbitMQ](./why-rabbitmq.md) - Message queue rationale
