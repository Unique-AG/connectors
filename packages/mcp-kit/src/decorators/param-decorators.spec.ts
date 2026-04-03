import { describe, it, expect } from 'vitest';
import 'reflect-metadata';
import { MCP_CTX_PARAM_INDEX, MCP_EXCLUDED_PARAMS } from '../constants';
import { Ctx } from './ctx.decorator';
import { McpExclude } from './mcp-exclude.decorator';
import type { ExcludedParamEntry } from './mcp-exclude.decorator';
import { scanMethodParams, getMcpInputParamIndices } from '../registry/param-scanner';

describe('@Ctx()', () => {
  it('stores parameter index in Reflect metadata under MCP_CTX_PARAM_INDEX at position 0', () => {
    class TestClass {
      method(_ctx: unknown) {}
    }
    Ctx()(TestClass.prototype, 'method', 0);
    const index = Reflect.getMetadata(MCP_CTX_PARAM_INDEX, TestClass.prototype, 'method');
    expect(index).toBe(0);
  });

  it('works at position 1', () => {
    class TestClass {
      method(_a: unknown, _ctx: unknown) {}
    }
    Ctx()(TestClass.prototype, 'method', 1);
    const index = Reflect.getMetadata(MCP_CTX_PARAM_INDEX, TestClass.prototype, 'method');
    expect(index).toBe(1);
  });

  it('works at position 2', () => {
    class TestClass {
      method(_a: unknown, _b: unknown, _ctx: unknown) {}
    }
    Ctx()(TestClass.prototype, 'method', 2);
    const index = Reflect.getMetadata(MCP_CTX_PARAM_INDEX, TestClass.prototype, 'method');
    expect(index).toBe(2);
  });

  it('last application wins when applied multiple times', () => {
    class TestClass {
      method(_a: unknown, _b: unknown) {}
    }
    Ctx()(TestClass.prototype, 'method', 0);
    Ctx()(TestClass.prototype, 'method', 1);
    const index = Reflect.getMetadata(MCP_CTX_PARAM_INDEX, TestClass.prototype, 'method');
    expect(index).toBe(1);
  });
});

describe('@McpExclude()', () => {
  it('stores ExcludedParamEntry with reason mcp-exclude in metadata', () => {
    class TestClass {
      method(_service: unknown) {}
    }
    McpExclude()(TestClass.prototype, 'method', 0);
    const entries: ExcludedParamEntry[] = Reflect.getMetadata(
      MCP_EXCLUDED_PARAMS,
      TestClass.prototype,
      'method',
    );
    expect(entries).toEqual([{ index: 0, reason: 'mcp-exclude' }]);
  });

  it('accumulates multiple excluded params', () => {
    class TestClass {
      method(_a: unknown, _b: unknown, _c: unknown) {}
    }
    McpExclude()(TestClass.prototype, 'method', 0);
    McpExclude()(TestClass.prototype, 'method', 2);
    const entries: ExcludedParamEntry[] = Reflect.getMetadata(
      MCP_EXCLUDED_PARAMS,
      TestClass.prototype,
      'method',
    );
    expect(entries).toHaveLength(2);
    expect(entries.some((e) => e.index === 0)).toBe(true);
    expect(entries.some((e) => e.index === 2)).toBe(true);
  });

  it('entries have correct index', () => {
    class TestClass {
      method(_a: unknown, _service: unknown) {}
    }
    McpExclude()(TestClass.prototype, 'method', 1);
    const entries: ExcludedParamEntry[] = Reflect.getMetadata(
      MCP_EXCLUDED_PARAMS,
      TestClass.prototype,
      'method',
    );
    expect(entries[0].index).toBe(1);
  });
});

describe('scanMethodParams()', () => {
  it('returns ctxParamIndex when @Ctx() is applied', () => {
    class TestClass {
      method(_ctx: unknown) {}
    }
    Ctx()(TestClass.prototype, 'method', 0);
    const result = scanMethodParams(TestClass.prototype, 'method');
    expect(result.ctxParamIndex).toBe(0);
  });

  it('returns ctxParamIndex undefined when no @Ctx()', () => {
    class TestClass {
      method(_a: unknown) {}
    }
    const result = scanMethodParams(TestClass.prototype, 'method');
    expect(result.ctxParamIndex).toBeUndefined();
  });

  it('returns explicitly excluded params from @McpExclude()', () => {
    class TestClass {
      method(_a: unknown, _service: unknown) {}
    }
    McpExclude()(TestClass.prototype, 'method', 1);
    const result = scanMethodParams(TestClass.prototype, 'method');
    expect(result.excludedParams).toEqual([{ index: 1, reason: 'mcp-exclude' }]);
  });
});

describe('getMcpInputParamIndices()', () => {
  it('with 3 params, ctx at index 1, no excluded returns [0, 2]', () => {
    const result = getMcpInputParamIndices(3, 1, []);
    expect(result).toEqual([0, 2]);
  });

  it('with 3 params, ctx at index 0, excluded at 2 returns [1]', () => {
    const result = getMcpInputParamIndices(3, 0, [{ index: 2, reason: 'mcp-exclude' }]);
    expect(result).toEqual([1]);
  });

  it('with 1 param, no ctx, no excluded returns [0]', () => {
    const result = getMcpInputParamIndices(1, undefined, []);
    expect(result).toEqual([0]);
  });
});
