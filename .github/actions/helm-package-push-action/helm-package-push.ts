/** 
deno run --allow-run --allow-read --allow-write=/tmp .github/actions/helm-package-push-action/helm-package-push.ts \
  --chart services/sharepoint-connector/deploy/helm-charts/sharepoint-connector \
  --destination /tmp \
  --registry oci://cmj1es1rt0000z1vsg6nd2pju.azurecr.io \
  --registry oci://registry2.example.com/charts
 */

import { Command } from "jsr:@cliffy/command@1.0.0-rc.7";
import { basename, join } from "jsr:@std/path@1";

async function exec(
  cmd: string[],
  options?: { cwd?: string }
): Promise<{ success: boolean; stdout: string; stderr: string }> {
  const command = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    cwd: options?.cwd,
    stdout: "piped",
    stderr: "piped",
  });
  const result = await command.output();
  return {
    success: result.success,
    stdout: new TextDecoder().decode(result.stdout),
    stderr: new TextDecoder().decode(result.stderr),
  };
}

async function getChartMetadata(chartPath: string): Promise<{ name: string; version: string }> {
  const chartYaml = await Deno.readTextFile(join(chartPath, "Chart.yaml"));
  const nameMatch = chartYaml.match(/^name:\s*(.+)$/m);
  const versionMatch = chartYaml.match(/^version:\s*(.+)$/m);
  if (!nameMatch) throw new Error("Could not find chart name in Chart.yaml");
  if (!versionMatch) throw new Error("Could not find chart version in Chart.yaml");
  return { name: nameMatch[1].trim(), version: versionMatch[1].trim() };
}

async function chartExists(
  registry: string,
  chartName: string,
  version: string
): Promise<boolean> {
  const result = await exec([
    "helm",
    "show",
    "chart",
    `${registry}/${chartName}`,
    "--version",
    version,
  ]);
  return result.success;
}

async function packageChart(
  chartPath: string,
  destination: string
): Promise<string> {
  const result = await exec([
    "helm",
    "package",
    chartPath,
    "--destination",
    destination,
  ]);
  if (!result.success) {
    throw new Error(`Failed to package chart: ${result.stderr}`);
  }
  const match = result.stdout.match(/Successfully packaged chart and saved it to: (.+\.tgz)/);
  if (!match) throw new Error("Could not find packaged chart path in output");
  return match[1].trim();
}

async function pushChart(chartPackage: string, registry: string): Promise<void> {
  const result = await exec(["helm", "push", chartPackage, registry]);
  if (!result.success) {
    throw new Error(`Failed to push chart: ${result.stderr}`);
  }
}

await new Command()
  .name("helm-package-push")
  .description("Package and push Helm charts to OCI registries")
  .option("-c, --chart <path:string>", "Path to the chart directory", {
    required: true,
  })
  .option("-r, --registry <registry:string>", "OCI registry (can be specified multiple times)", {
    required: true,
    collect: true,
  })
  .option("-d, --destination <path:string>", "Destination directory for packaged chart", {
    default: ".",
  })
  .action(async ({ chart, registry: registries, destination }) => {
    const { name, version } = await getChartMetadata(chart);
    console.log(`Chart: ${name}`);
    console.log(`Version: ${version}`);
    console.log(`Registries: ${registries.join(", ")}`);

    let chartPackage: string | null = null;

    for (const registry of registries) {
      console.log(`\n→ Processing registry: ${registry}`);

      const exists = await chartExists(registry, name, version);
      if (exists) {
        console.log(`  ♻️ Chart ${name}:${version} already exists, skipping.`);
        continue;
      }

      console.log(`  → Chart does not exist, packaging and pushing...`);

      if (!chartPackage) {
        chartPackage = await packageChart(chart, destination);
        console.log(`  ✓ Packaged: ${basename(chartPackage)}`);
      }

      await pushChart(chartPackage, registry);
      console.log(`  ✓ Pushed to ${registry}`);
    }

    if (chartPackage) {
      await Deno.remove(chartPackage);
    }

    console.log("\n✓ Done");
  })
  .parse(Deno.args);
