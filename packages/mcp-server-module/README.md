# MCP NestJS Module to turn a NestJS application into an MCP server

This module implements the MCP server interface for NestJS applications.

This is an extension of the MCP-Nest module developed by [@rekog-labs/MCP-Nest](https://github.com/rekog-labs/MCP-Nest/tree/main).

## Prompts

Example:
```ts
const HelloWorldPromptSchema = z.object({
  planet: z.string().prefault('World').meta({
    id: 'planet',
    title: 'Planet',
    description: 'The planet to say hello to',
    examples: ['Earth', 'Moon', 'Mars']
  }),
  what: z.string().prefault('Hello').meta({
    id: 'what',
    title: 'What',
    description: 'The word to say hello with',
    examples: ['Hello', 'Hi', 'Hey']
  })
});

@Injectable()
export class HelloWorldPrompt {
  @Prompt({
    name: 'foo',
    description: 'bar',
    parameters: HelloWorldPromptSchema
  })
  public helloWorld({ planet, what }: z.infer<typeof HelloWorldPromptSchema>): GetPromptResult {
    return {
      description: 'Says Hello World!',
      messages: [
        {
          role: 'user',
          content: {
            type: 'text',
            text: `${what} ${planet}!`,
          },
        },
      ],
    };
  }
}
```

## Elicitation

Use `context.elicit()` to collect structured form data from the user, or `context.elicitUrl()` to guide the user through a URL-based flow such as OAuth.

### Form-based elicitation

Example:
```ts
@Injectable()
export class MyTool {
  @Tool({
    name: 'create-item',
    description: 'Creates an item after collecting details from the user',
  })
  async createItem(_args: unknown, context: Context): Promise<CallToolResult> {
    const result = await context.elicit(
      z.object({
        name: z.string().meta({ title: 'Name', description: 'Item name' }),
        confirm: z.boolean().meta({ title: 'Confirm', description: 'Are you sure?' }),
      }),
      'Please provide the details for the new item',
    );

    if (result.action !== 'accept') {
      return { content: [{ type: 'text', text: 'Cancelled.' }] };
    }

    // result.content is typed as { name: string; confirm: boolean }
    return { content: [{ type: 'text', text: `Created: ${result.content.name}` }] };
  }
}
```

### URL-based elicitation (OAuth-style)

Example:
```ts
@Injectable()
export class MyTool {
  @Tool({
    name: 'connect-account',
    description: 'Connects an external account via OAuth',
  })
  async connectAccount(_args: unknown, context: Context): Promise<CallToolResult> {
    const elicitationId = crypto.randomUUID();

    const result = await context.elicitUrl({
      elicitationId,
      message: 'Authorize access to your account',
      url: `https://example.com/oauth/authorize?state=${elicitationId}`,
    });

    if (result.action !== 'accept') {
      return { content: [{ type: 'text', text: 'Authorization cancelled.' }] };
    }

    // OAuth callback has completed server-side; notify the client
    await result.sendCompletionNotification();
    return { content: [{ type: 'text', text: 'Account connected.' }] };
  }
}
```

## Credits

- [@rekog-labs/MCP-Nest](https://github.com/rekog-labs/MCP-Nest/tree/main)