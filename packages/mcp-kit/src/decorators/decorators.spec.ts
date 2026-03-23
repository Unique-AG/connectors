import 'reflect-metadata';
import { z } from 'zod';
import { describe, it, expect } from 'vitest';
import { Tool, type ToolMetadata } from './tool.decorator';
import { Resource, type ResourceMetadata } from './resource.decorator';
import { Prompt, type PromptMetadata } from './prompt.decorator';
import { MCP_TOOL_METADATA, MCP_RESOURCE_METADATA, MCP_PROMPT_METADATA } from '../constants';

describe('@Tool()', () => {
  describe('camelToSnakeCase', () => {
    it('converts searchEmails to search_emails', () => {
      class TestService {
        @Tool({ description: 'Search emails' })
        searchEmails() {}
      }
      const metadata: ToolMetadata = Reflect.getMetadata(
        MCP_TOOL_METADATA,
        TestService.prototype.searchEmails,
      );
      expect(metadata.name).toBe('search_emails');
    });

    it('converts parseHTMLContent to parse_html_content', () => {
      class TestService {
        @Tool({ description: 'Parse HTML' })
        parseHTMLContent() {}
      }
      const metadata: ToolMetadata = Reflect.getMetadata(
        MCP_TOOL_METADATA,
        TestService.prototype.parseHTMLContent,
      );
      expect(metadata.name).toBe('parse_html_content');
    });

    it('converts getURL to get_url', () => {
      class TestService {
        @Tool({ description: 'Get URL' })
        getURL() {}
      }
      const metadata: ToolMetadata = Reflect.getMetadata(
        MCP_TOOL_METADATA,
        TestService.prototype.getURL,
      );
      expect(metadata.name).toBe('get_url');
    });
  });

  it('derives name from method name', () => {
    class TestService {
      @Tool({ description: 'Send message' })
      sendMessage() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.sendMessage,
    );
    expect(metadata.name).toBe('send_message');
    expect(metadata.methodName).toBe('sendMessage');
  });

  it('overrides name when name option is provided', () => {
    class TestService {
      @Tool({ name: 'custom_name', description: 'Custom tool' })
      sendMessage() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.sendMessage,
    );
    expect(metadata.name).toBe('custom_name');
  });

  it('wraps parameters shorthand Record to ZodObject', () => {
    class TestService {
      @Tool({ description: 'Add numbers', parameters: { a: z.number(), b: z.number() } })
      addNumbers() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.addNumbers,
    );
    expect(metadata.parameters).toBeInstanceOf(z.ZodObject);
    const shape = metadata.parameters.shape;
    expect(shape.a).toBeInstanceOf(z.ZodNumber);
    expect(shape.b).toBeInstanceOf(z.ZodNumber);
  });

  it('passes ZodObject parameters through unchanged', () => {
    const schema = z.object({ query: z.string() });
    class TestService {
      @Tool({ description: 'Search', parameters: schema })
      search() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.search,
    );
    expect(metadata.parameters).toBe(schema);
  });

  it('defaults parameters to empty ZodObject when omitted', () => {
    class TestService {
      @Tool({ description: 'No params tool' })
      noParams() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.noParams,
    );
    expect(metadata.parameters).toBeInstanceOf(z.ZodObject);
    expect(Object.keys(metadata.parameters.shape)).toHaveLength(0);
  });

  it('propagates title to annotations.title', () => {
    class TestService {
      @Tool({ description: 'My tool', title: 'My Tool Title' })
      myTool() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.myTool,
    );
    expect(metadata.annotations.title).toBe('My Tool Title');
    expect(metadata.title).toBe('My Tool Title');
  });

  it('explicit annotations.title takes precedence over title', () => {
    class TestService {
      @Tool({
        description: 'My tool',
        title: 'General Title',
        annotations: { title: 'Explicit Annotation Title' },
      })
      myTool() {}
    }
    const metadata: ToolMetadata = Reflect.getMetadata(
      MCP_TOOL_METADATA,
      TestService.prototype.myTool,
    );
    expect(metadata.annotations.title).toBe('Explicit Annotation Title');
  });

  it('stores metadata under MCP_TOOL_METADATA symbol', () => {
    class TestService {
      @Tool({ description: 'Test' })
      testMethod() {}
    }
    const metadata = Reflect.getMetadata(MCP_TOOL_METADATA, TestService.prototype.testMethod);
    expect(metadata).toBeDefined();
    expect(metadata.description).toBe('Test');
  });
});

describe('@Resource()', () => {
  it('static URI produces kind static with empty params', () => {
    class TestService {
      @Resource({ uri: 'config://app/settings' })
      getSettings() {}
    }
    const metadata: ResourceMetadata = Reflect.getMetadata(
      MCP_RESOURCE_METADATA,
      TestService.prototype.getSettings,
    );
    expect(metadata.kind).toBe('static');
    expect(metadata.templateParams).toHaveLength(0);
  });

  it('URI with {user_id} produces kind template with templateParams', () => {
    class TestService {
      @Resource({ uri: 'users://{user_id}/profile' })
      getUserProfile() {}
    }
    const metadata: ResourceMetadata = Reflect.getMetadata(
      MCP_RESOURCE_METADATA,
      TestService.prototype.getUserProfile,
    );
    expect(metadata.kind).toBe('template');
    expect(metadata.templateParams).toContain('user_id');
  });

  it('URI with {+path} produces wildcard templateParam', () => {
    class TestService {
      @Resource({ uri: 'files://{+path}' })
      getFile() {}
    }
    const metadata: ResourceMetadata = Reflect.getMetadata(
      MCP_RESOURCE_METADATA,
      TestService.prototype.getFile,
    );
    expect(metadata.kind).toBe('template');
    expect(metadata.templateParams).toContain('path');
  });

  it('mixed URI parses templateParams correctly', () => {
    class TestService {
      @Resource({ uri: 'repo://{owner}/{repo}/files/{+path}' })
      getRepoFile() {}
    }
    const metadata: ResourceMetadata = Reflect.getMetadata(
      MCP_RESOURCE_METADATA,
      TestService.prototype.getRepoFile,
    );
    expect(metadata.kind).toBe('template');
    expect(metadata.templateParams).toContain('path');
    expect(metadata.templateParams).toContain('owner');
    expect(metadata.templateParams).toContain('repo');
  });

  it('name defaults to method name with camelCase preserved', () => {
    class TestService {
      @Resource({ uri: 'static://resource' })
      getMyResource() {}
    }
    const metadata: ResourceMetadata = Reflect.getMetadata(
      MCP_RESOURCE_METADATA,
      TestService.prototype.getMyResource,
    );
    expect(metadata.name).toBe('getMyResource');
  });
});

describe('@Prompt()', () => {
  describe('camelToKebabCase', () => {
    it('converts composeOutreach to compose-outreach', () => {
      class TestService {
        @Prompt({ description: 'Compose outreach' })
        composeOutreach() {}
      }
      const metadata: PromptMetadata = Reflect.getMetadata(
        MCP_PROMPT_METADATA,
        TestService.prototype.composeOutreach,
      );
      expect(metadata.name).toBe('compose-outreach');
    });
  });

  it('derives name from method name', () => {
    class TestService {
      @Prompt({ description: 'Write email' })
      writeEmail() {}
    }
    const metadata: PromptMetadata = Reflect.getMetadata(
      MCP_PROMPT_METADATA,
      TestService.prototype.writeEmail,
    );
    expect(metadata.name).toBe('write-email');
    expect(metadata.methodName).toBe('writeEmail');
  });

  it('wraps parameters shorthand Record to ZodObject', () => {
    class TestService {
      @Prompt({ description: 'Greet user', parameters: { name: z.string(), formal: z.boolean() } })
      greetUser() {}
    }
    const metadata: PromptMetadata = Reflect.getMetadata(
      MCP_PROMPT_METADATA,
      TestService.prototype.greetUser,
    );
    expect(metadata.parameters).toBeInstanceOf(z.ZodObject);
    const shape = metadata.parameters!.shape;
    expect(shape.name).toBeInstanceOf(z.ZodString);
    expect(shape.formal).toBeInstanceOf(z.ZodBoolean);
  });

  it('stores title separately from name', () => {
    class TestService {
      @Prompt({ name: 'compose-email', title: 'Compose Email', description: 'Compose an email' })
      composeEmail() {}
    }
    const metadata: PromptMetadata = Reflect.getMetadata(
      MCP_PROMPT_METADATA,
      TestService.prototype.composeEmail,
    );
    expect(metadata.name).toBe('compose-email');
    expect(metadata.title).toBe('Compose Email');
  });
});
