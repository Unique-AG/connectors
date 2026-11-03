import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  applyTerraform,
  createTerraformLookup,
  parseProviders,
  planTerraform,
  retargetConstraint,
  satisfies,
} from './terraform.mjs';

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
  const run = (files, lookup, locks) =>
    planTerraform({ files, locks, lookup, now: NOW, cooldownDays: 3 });
  const FOLDER = 'services/a/deploy/terraform/x';
  const lockOf = (versions) => ({
    [`${FOLDER}/.terraform.lock.hcl`]: Object.entries(versions)
      .map(
        ([type, version]) =>
          `provider "registry.terraform.io/hashicorp/${type}" {\n  version     = "${version}"\n  constraints = "x"\n}\n`,
      )
      .join('\n'),
  });

  it('reports nothing when every constraint holds', async () => {
    const lookup = lookupOf();
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', {
        azurerm: '>= 4, < 6',
        time: '~> 0.12',
      }),
    };
    const locks = lockOf({ azurerm: '4.9.0', time: '0.13.1' });
    assert.deepStrictEqual(await run(files, lookup, locks), { candidates: [], needsPerson: [] });
    assert.deepStrictEqual(lookup.calls.sort(), [
      'hashicorp/terraform',
      'hashicorp/terraform-provider-azurerm',
      'hashicorp/terraform-provider-time',
    ]);
  });

  it('proposes a pull request for a provider whose newest eligible release is outside the constraint', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '~> 3' }),
    };
    assert.deepStrictEqual(await run(files, lookupOf()), {
      candidates: [
        {
          ecosystem: 'terraform',
          name: 'azurerm',
          from: '~> 3',
          to: '4.9.0',
          direct: true,
          data: { source: 'hashicorp/azurerm', major: true },
        },
      ],
      needsPerson: [],
    });
  });

  it('proposes a lock update when the lock is behind a release inside the constraint', async () => {
    const files = { [`${FOLDER}/versions.tf`]: versionsTf('~> 1.10', { azurerm: '>= 3, < 6' }) };
    const behind = await run(files, lookupOf(), lockOf({ azurerm: '4.5.0' }));
    assert.deepStrictEqual(behind.candidates, [
      {
        ecosystem: 'terraform',
        name: 'azurerm',
        from: '4.5.0',
        to: '4.9.0',
        direct: true,
        data: { source: 'hashicorp/azurerm' },
      },
    ]);
    const major = await run(files, lookupOf(), lockOf({ azurerm: '3.117.0' }));
    assert.deepStrictEqual(major.candidates[0].data, { source: 'hashicorp/azurerm', major: true });
  });

  it('proposes a lock for a module that has none', async () => {
    const files = { [`${FOLDER}/versions.tf`]: versionsTf('~> 1.10', { azurerm: '>= 4, < 6' }) };
    const { candidates } = await run(files, lookupOf());
    assert.deepStrictEqual(
      candidates.map(({ from, to }) => [from, to]),
      [['no lock', '4.9.0']],
    );
  });

  it('ignores a release inside the cooldown and a prerelease', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '< 5' }),
    };
    assert.deepStrictEqual(await run(files, lookupOf(), lockOf({ azurerm: '4.9.0' })), {
      candidates: [],
      needsPerson: [],
    });
  });

  it('reports the core version when it is outside required_version', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 0.14', {}),
    };
    const { candidates, needsPerson } = await run(files, lookupOf());
    assert.deepStrictEqual(candidates, []);
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
    const { candidates, needsPerson } = await run(files, lookupOf());
    assert.deepStrictEqual(needsPerson, []);
    assert.strictEqual(candidates.length, 1);
    assert.strictEqual(candidates[0].from, '~> 3');
  });

  it('asks for the repository of the provider type, not of the local name', async () => {
    const lookup = lookupOf();
    const files = {
      'a/versions.tf': `terraform {
  required_providers {
    azure = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}
`,
    };
    const { candidates } = await run(files, lookup);
    assert.deepStrictEqual(lookup.calls, ['hashicorp/terraform-provider-azurerm']);
    assert.deepStrictEqual(
      candidates.map(({ name, to }) => [name, to]),
      [['azure', '4.9.0']],
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
    const { candidates, needsPerson } = await run(files, lookup);
    assert.deepStrictEqual(
      candidates.map(({ name, to }) => [name, to]),
      [['azurerm', '4.9.0']],
    );
    assert.deepStrictEqual(
      needsPerson.map(({ name, reason }) => [name, reason]),
      [['time', 'The release lookup failed.']],
    );
  });

  it('reports a constraint that cannot be widened apart from a failed lookup', async () => {
    const files = {
      'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', { azurerm: '!= 4.9.0' }),
    };
    const { candidates, needsPerson } = await run(files, lookupOf());
    assert.deepStrictEqual(candidates, []);
    assert.deepStrictEqual(
      needsPerson.map(({ name, reason }) => [name, reason]),
      [['azurerm', 'The constraint != 4.9.0 cannot be widened to 4.9.0.']],
    );
  });
});

describe('retargetConstraint', () => {
  for (const [constraint, version, expected] of [
    ['~> 3', '4.9.0', '~> 4'],
    ['~> 0.12', '1.0.0', '~> 1.0'],
    ['~> 0.12', '0.13.1', '~> 0.12'],
    ['~> 1.2.3', '1.3.4', '~> 1.3.4'],
    ['>= 4, < 6', '7.1.0', '>= 4, < 8'],
    ['>= 4, < 6', '6.0.0', '>= 4, < 7'],
    ['< 6.2', '7.1.3', '< 7.2'],
    ['<= 4', '4.0.1', '<= 4.0.1'],
    ['= 1.2.3', '1.2.4', '= 1.2.4'],
    ['1.2.3', '1.2.4', '1.2.4'],
    ['>= 4, < 6', '5.0.0', '>= 4, < 6'],
    ['>= 1, != 1.2.3', '1.2.3', '>= 1'],
    ['!= 1.2.3, >= 1', '1.2.3', '>= 1'],
    ['~> 3, != 4.9.0', '4.9.0', '~> 4'],
    ['>= 1, != 1.2.2', '1.2.3', '>= 1, != 1.2.2'],
  ]) {
    it(`${constraint} fits ${version} as ${expected}`, () => {
      assert.strictEqual(retargetConstraint(constraint, version), expected);
    });
  }

  it('throws when dropping the exclusion leaves nothing', () => {
    assert.throws(
      () => retargetConstraint('!= 1.2.3', '1.2.3'),
      /The constraint != 1\.2\.3 cannot be widened to 1\.2\.3\./,
    );
  });
});

describe('applyTerraform', () => {
  const files = {
    'services/a/deploy/terraform/x/versions.tf': versionsTf('~> 1.10', {
      azurerm: '~> 3',
      time: '~> 0.12',
    }),
    'services/b/deploy/terraform/y/versions.tf': versionsTf('~> 1.10', { azurerm: '>= 4, < 6' }),
    'services/c/deploy/terraform/z/versions.tf': versionsTf('~> 1.10', { random: '~> 3' }),
  };

  it('changes only the named provider, in the files that need it', () => {
    const changed = applyTerraform(files, { to: '4.9.0', data: { source: 'hashicorp/azurerm' } });
    assert.deepStrictEqual(Object.keys(changed), ['services/a/deploy/terraform/x/versions.tf']);
    const text = changed['services/a/deploy/terraform/x/versions.tf'];
    assert.match(text, /azurerm = \{\n\s+source\s+= "hashicorp\/azurerm"\n\s+version = "~> 4"/);
    assert.match(text, /version = "~> 0\.12"/);
    assert.match(text, /required_version = "~> 1\.10"/);
  });

  it('widens a range in every folder when the release is outside it', () => {
    const changed = applyTerraform(files, { to: '7.0.0', data: { source: 'hashicorp/azurerm' } });
    assert.deepStrictEqual(Object.keys(changed).sort(), [
      'services/a/deploy/terraform/x/versions.tf',
      'services/b/deploy/terraform/y/versions.tf',
    ]);
    assert.match(changed['services/b/deploy/terraform/y/versions.tf'], /version = ">= 4, < 8"/);
  });

  it('retargets every local name that binds the same source', () => {
    const module = (localName) => `terraform {
  required_providers {
    ${localName} = {
      source  = "hashicorp/google"
      version = "~> 5"
    }
  }
}
`;
    const changed = applyTerraform(
      { 'a/versions.tf': module('google'), 'b/versions.tf': module('gcp') },
      { to: '6.1.0', data: { source: 'hashicorp/google' } },
    );
    assert.match(changed['a/versions.tf'], /google = \{[^}]*version = "~> 6"/);
    assert.match(changed['b/versions.tf'], /gcp = \{[^}]*version = "~> 6"/);
  });

  it('returns nothing when no file names the provider', () => {
    assert.deepStrictEqual(
      applyTerraform(files, { to: '9.0.0', data: { source: 'hashicorp/google' } }),
      {},
    );
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
