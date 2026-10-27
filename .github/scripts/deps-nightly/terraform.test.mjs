import assert from 'node:assert';
import { describe, it } from 'node:test';
import { createTerraformLookup, parseProviders, planTerraform, satisfies } from './terraform.mjs';

const NOW = Date.parse('2026-10-27T00:00:00Z');
const DAY_MS = 24 * 60 * 60 * 1000;
const daysAgo = (days) => new Date(NOW - days * DAY_MS).toISOString();

const versionsTf = (requiredVersion, providers) => `terraform {
  required_version = "${requiredVersion}"
  required_providers {
${Object.entries(providers)
  .map(
    ([name, constraint]) => `    ${name} = {
      source  = "hashicorp/${name}"
      version = "${constraint}"
    }`,
  )
  .join('\n')}
  }
}
`;

describe('parseProviders', () => {
  it('reads the required version and every provider entry', () => {
    const text = `# comment { with a brace
terraform {
  required_version = "~> 1.10"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4, < 6"
    }
    time = {
      source = "hashicorp/time"
      version = "~> 0.12"
    }
  }
}

provider "azurerm" {
  features {}
}
`;
    assert.deepStrictEqual(parseProviders(text), {
      requiredVersion: '~> 1.10',
      providers: [
        { name: 'azurerm', source: 'hashicorp/azurerm', constraint: '>= 4, < 6' },
        { name: 'time', source: 'hashicorp/time', constraint: '~> 0.12' },
      ],
    });
  });

  it('returns no providers when the file has none', () => {
    assert.deepStrictEqual(parseProviders('terraform {\n  required_version = "~> 1.10"\n}\n'), {
      requiredVersion: '~> 1.10',
      providers: [],
    });
  });
});

describe('satisfies', () => {
  for (const [version, constraint, expected] of [
    ['1.10.0', '~> 1.10', true],
    ['1.99.9', '~> 1.10', true],
    ['2.0.0', '~> 1.10', false],
    ['1.9.9', '~> 1.10', false],
    ['3.117.1', '~> 3', true],
    ['4.0.0', '~> 3', false],
    ['0.12.0', '~> 0.12', true],
    ['0.13.1', '~> 0.12', true],
    ['1.0.0', '~> 0.12', false],
    ['1.2.9', '~> 1.2.3', true],
    ['1.3.0', '~> 1.2.3', false],
    ['1.2.2', '~> 1.2.3', false],
    ['4.5.0', '>= 4, < 6', true],
    ['6.0.0', '>= 4, < 6', false],
    ['3.9.9', '>= 4, < 6', false],
    ['4.0.0', '> 4', false],
    ['4.0.1', '> 4', true],
    ['4.0.0', '<= 4', true],
    ['4.0.1', '<= 4', false],
    ['4.0.0', '< 4', false],
    ['3.9.9', '< 4', true],
    ['1.2.3', '= 1.2.3', true],
    ['1.2.4', '= 1.2.3', false],
    ['1.2.3', '1.2.3', true],
    ['1.2.4', '1.2.3', false],
    ['1.2.4', '!= 1.2.3', true],
  ]) {
    it(`${version} against ${constraint} is ${expected}`, () => {
      assert.strictEqual(satisfies(version, constraint), expected);
    });
  }

  it('throws on a constraint it cannot read', () => {
    assert.throws(() => satisfies('1.0.0', '~> latest'), /Not a version constraint/);
  });
});

describe('planTerraform', () => {
  const releases = {
    'hashicorp/terraform': [
      { tag: '1.10.5', publishedAt: daysAgo(40) },
      { tag: '1.11.0-rc1', publishedAt: daysAgo(10) },
    ],
    'hashicorp/terraform-provider-azurerm': [
      { tag: '4.9.0', publishedAt: daysAgo(10) },
      { tag: '5.0.0', publishedAt: daysAgo(1) },
    ],
    'hashicorp/terraform-provider-time': [{ tag: '0.13.1', publishedAt: daysAgo(10) }],
  };
  const lookupOf = (overrides = {}) => {
    const calls = [];
    return {
      calls,
      releases: async (repo) => {
        calls.push(repo);
        const found = overrides[repo] ?? releases[repo];
        if (found instanceof Error) {
          throw found;
        }
        return found ?? [];
      },
    };
  };
  const run = (files, lookup) => planTerraform({ files, lookup, now: NOW, cooldownDays: 3 });

  it('reports nothing when every constraint holds', async () => {
    const lookup = lookupOf();
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', {
        azurerm: '>= 4, < 6',
        time: '~> 0.12',
      }),
    };
    assert.deepStrictEqual(await run(files, lookup), { needsPerson: [] });
    assert.deepStrictEqual(lookup.calls.sort(), [
      'hashicorp/terraform',
      'hashicorp/terraform-provider-azurerm',
      'hashicorp/terraform-provider-time',
    ]);
  });

  it('reports a provider whose newest eligible release is outside the constraint', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '~> 3' }),
    };
    assert.deepStrictEqual(await run(files, lookupOf()), {
      needsPerson: [
        {
          ecosystem: 'terraform',
          name: 'azurerm',
          reason:
            'The newest release of azurerm is 4.9.0. It is outside "~> 3" in services/a/deploy/terraform/x.',
        },
      ],
    });
  });

  it('ignores a release inside the cooldown and a prerelease', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '< 5' }),
    };
    assert.deepStrictEqual(await run(files, lookupOf()), { needsPerson: [] });
  });

  it('reports the core version when it is outside required_version', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 0.14', {}),
    };
    const { needsPerson } = await run(files, lookupOf());
    assert.deepStrictEqual(
      needsPerson.map(({ name, reason }) => [name, reason]),
      [
        [
          'terraform',
          'The newest release of terraform is 1.10.5. It is outside "~> 0.14" in services/a/deploy/terraform/x.',
        ],
      ],
    );
  });

  it('groups the same provider across folders into one entry', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '~> 3' }),
      'services/b/deploy/terraform/y/versions.tf': versionsTf('~> 1.10', { azurerm: '~> 3' }),
      'services/c/deploy/terraform/z/versions.tf': versionsTf('~> 1.10', { azurerm: '>= 4, < 6' }),
    };
    const { needsPerson } = await run(files, lookupOf());
    assert.strictEqual(needsPerson.length, 1);
    assert.strictEqual(
      needsPerson[0].reason,
      'The newest release of azurerm is 4.9.0. It is outside "~> 3" in services/a/deploy/terraform/x, services/b/deploy/terraform/y.',
    );
  });

  it('reports a failed lookup and still checks the others', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', {
        azurerm: '~> 3',
        time: '~> 0.12',
      }),
    };
    const lookup = lookupOf({ 'hashicorp/terraform-provider-time': new Error('boom') });
    const { needsPerson } = await run(files, lookup);
    assert.deepStrictEqual(needsPerson.map(({ name, reason }) => [name, reason]).sort(), [
      [
        'azurerm',
        'The newest release of azurerm is 4.9.0. It is outside "~> 3" in services/a/deploy/terraform/x.',
      ],
      ['time', 'The release lookup failed.'],
    ]);
  });
});

describe('createTerraformLookup', () => {
  const answer = (body, status = 200) => ({ status, json: async () => body });
  const body = [
    { tag_name: 'v4.9.0', published_at: '2026-10-01T00:00:00Z', draft: false, prerelease: false },
    {
      tag_name: 'v5.0.0-beta1',
      published_at: '2026-10-02T00:00:00Z',
      draft: false,
      prerelease: true,
    },
    { tag_name: 'v5.0.0', published_at: '2026-10-03T00:00:00Z', draft: true, prerelease: false },
    { tag_name: '1.10.5', published_at: '2026-09-01T00:00:00Z', draft: false, prerelease: false },
  ];

  it('sends the token, skips drafts and prereleases and strips the v', async () => {
    let seen;
    const fetchImpl = async (url, options) => {
      seen = { url, options };
      return answer(body);
    };
    const releases = await createTerraformLookup('secret', fetchImpl).releases(
      'hashicorp/terraform-provider-azurerm',
    );
    assert.strictEqual(
      seen.url,
      'https://api.github.com/repos/hashicorp/terraform-provider-azurerm/releases?per_page=30',
    );
    assert.strictEqual(seen.options.headers.Authorization, 'Bearer secret');
    assert.ok(seen.options.signal instanceof AbortSignal);
    assert.deepStrictEqual(releases, [
      { tag: '4.9.0', publishedAt: '2026-10-01T00:00:00Z' },
      { tag: '1.10.5', publishedAt: '2026-09-01T00:00:00Z' },
    ]);
  });

  it('sends no Authorization header without a token', async () => {
    let headers;
    const fetchImpl = async (_url, options) => {
      headers = options.headers;
      return answer([]);
    };
    await createTerraformLookup(undefined, fetchImpl).releases('hashicorp/terraform');
    assert.strictEqual('Authorization' in headers, false);
  });

  it('throws on a non-200 answer so the plan reports it', async () => {
    const fetchImpl = async () => answer({}, 403);
    await assert.rejects(
      createTerraformLookup('secret', fetchImpl).releases('hashicorp/terraform'),
      /GitHub answered 403/,
    );
  });
});
