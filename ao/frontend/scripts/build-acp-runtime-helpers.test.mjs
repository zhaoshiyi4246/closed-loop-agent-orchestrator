// @vitest-environment node
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	readdirSync,
	rmSync,
	symlinkSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
	createWorkDirectory,
	npmInvocation,
	patchClaudeRetryDetails,
	pruneNodeDistribution,
	runtimeSourceFiles,
	windowsNodeExtraction,
} from "./build-acp-runtime-helpers.mjs";

const temporaryDirectories = [];

describe.skipIf(process.platform !== "win32")("Windows Node ZIP extraction", () => {
	function fixture(names) {
		const root = temporaryDirectory();
		const archive = join(root, "node's archive.zip");
		const literal = (value) => `'${value.replaceAll("'", "''")}'`;
		const script = `$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::Open(${literal(archive)}, [IO.Compression.ZipArchiveMode]::Create)
try { foreach ($name in @(${names.map(literal).join(",")})) {
  $entry=$zip.CreateEntry($name); $writer=[IO.StreamWriter]::new($entry.Open())
  try { $writer.Write('fixture-runtime') } finally { $writer.Dispose() }
} } finally { $zip.Dispose() }`;
		const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { encoding: "utf8", windowsHide: true });
		expect(result.status, result.stderr).toBe(0);
		return { root, archive };
	}

	it("extracts only exact runtime entries despite deeply nested npm paths", () => {
		const { root, archive } = fixture(["node-test/node.exe", "node-test/LICENSE", `node-test/node_modules/${"nested/".repeat(45)}tool.js`]);
		const destination = join(root, "deep-build-root-".repeat(5), "node's runtime");
		const invocation = windowsNodeExtraction(archive, destination, "node-test");
		const result = spawnSync(invocation.command, invocation.args, { encoding: "utf8", windowsHide: true });
		expect(result.status, result.stderr).toBe(0);
		expect(readdirSync(destination).sort()).toEqual(["LICENSE", "node.exe"]);
		expect(readFileSync(join(destination, "node.exe"), "utf8")).toBe("fixture-runtime");
	}, 15000);

	it.each([
		["missing", ["node-test/node.exe"]],
		["duplicate", ["node-test/node.exe", "node-test/LICENSE", "node-test/LICENSE"]],
	])("rejects %s required entries before creating output", (_label, names) => {
		const { root, archive } = fixture(names);
		const destination = join(root, "node");
		const invocation = windowsNodeExtraction(archive, destination, "node-test");
		const result = spawnSync(invocation.command, invocation.args, { encoding: "utf8", windowsHide: true });
		expect(result.status).not.toBe(0);
		expect(result.stderr).toContain("Missing, empty or duplicate Node runtime entry");
		expect(existsSync(destination)).toBe(false);
	}, 15000);
});

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) {
		rmSync(directory, { recursive: true, force: true });
	}
});

describe("createWorkDirectory", () => {
	it("places extraction on the output filesystem", () => {
		const outputRoot = temporaryDirectory();
		const workDirectory = createWorkDirectory(outputRoot);

		expect(dirname(workDirectory)).toBe(outputRoot);
		expect(existsSync(workDirectory)).toBe(true);
	});
});

describe("runtimeSourceFiles", () => {
	it("packages and fingerprints the ACP runtime manifest", () => {
		expect(runtimeSourceFiles()).toEqual([
			"package.json",
			"package-lock.json",
		]);
	});
});

describe("npmInvocation", () => {
	it("runs the parent npm CLI through Node on Windows", () => {
		expect(
			npmInvocation(["ci", "--omit=dev"], {
				platform: "win32",
				execPath: "C:\\node\\node.exe",
				npmExecPath: "C:\\node\\node_modules\\npm\\bin\\npm-cli.js",
				commandInterpreter: "C:\\Windows\\System32\\cmd.exe",
			}),
		).toEqual({
			command: "C:\\node\\node.exe",
			args: ["C:\\node\\node_modules\\npm\\bin\\npm-cli.js", "ci", "--omit=dev"],
		});
	});

	it("falls back to cmd.exe for a directly invoked Windows build script", () => {
		expect(
			npmInvocation(["ci"], {
				platform: "win32",
				npmExecPath: null,
				commandInterpreter: "C:\\Windows\\System32\\cmd.exe",
			}),
		).toEqual({
			command: "C:\\Windows\\System32\\cmd.exe",
			args: ["/d", "/s", "/c", "npm.cmd", "ci"],
		});
	});

	it("invokes npm directly on Unix when no parent npm CLI is available", () => {
		expect(npmInvocation(["ci"], { platform: "linux", npmExecPath: null })).toEqual({
			command: "npm",
			args: ["ci"],
		});
	});
});

describe("patchClaudeRetryDetails", () => {
	it("keeps Claude's retry delay in the published session failure", () => {
		const adapterPath = join(temporaryDirectory(), "acp-agent.js");
		writeFileSync(adapterPath, `
                            case "api_retry": {
                                const title = "retrying";
                                await publishSessionFailure(message.error_status === null
                                    ? "transport_lost"
                                    : providerFailureCategory(message.error), {
                                    title,
                                    severity: "warning",
                                });
                                break;
                            }
                            case "model_refusal_fallback": {
`);

		expect(patchClaudeRetryDetails(adapterPath)).toBe(true);
		expect(patchClaudeRetryDetails(adapterPath)).toBe(false);
		const patched = readFileSync(adapterPath, "utf8");
		expect(patched).toContain("message.retry_delay_ms / 1000");
		expect(patched).toContain("Trying again in ${retryDelay}.");
		expect(patched).toContain("details: retryDetails");
	});
});

describe("pruneNodeDistribution", () => {
	it("removes Unix package-manager links before deleting their targets", () => {
		const nodeRoot = temporaryDirectory();
		const bin = join(nodeRoot, "bin");
		const npmBin = join(nodeRoot, "lib", "node_modules", "npm", "bin");
		mkdirSync(bin, { recursive: true });
		mkdirSync(npmBin, { recursive: true });
		writeFileSync(join(bin, "node"), "node");
		writeFileSync(join(npmBin, "npm-cli.js"), "npm");
		writeFileSync(join(npmBin, "npx-cli.js"), "npx");
		symlinkSync("../lib/node_modules/npm/bin/npm-cli.js", join(bin, "npm"));
		symlinkSync("../lib/node_modules/npm/bin/npx-cli.js", join(bin, "npx"));
		symlinkSync("../lib/node_modules/corepack/dist/corepack.js", join(bin, "corepack"));

		pruneNodeDistribution(nodeRoot);

		expect(readdirSync(bin)).toEqual(["node"]);
		expect(existsSync(join(nodeRoot, "lib"))).toBe(false);
	});

	it("removes package-manager files and modules from a Windows distribution", () => {
		const nodeRoot = temporaryDirectory();
		writeFileSync(join(nodeRoot, "node.exe"), "node");
		writeFileSync(join(nodeRoot, "LICENSE"), "license");
		for (const name of ["corepack", "corepack.cmd", "corepack.ps1", "npm", "npm.cmd", "npm.ps1", "npx", "npx.cmd", "npx.ps1", "install_tools.bat", "nodevars.bat"]) {
			writeFileSync(join(nodeRoot, name), name);
		}
		mkdirSync(join(nodeRoot, "node_modules", "npm"), { recursive: true });

		pruneNodeDistribution(nodeRoot);

		expect(readdirSync(nodeRoot).sort()).toEqual(["LICENSE", "node.exe"]);
	});
});

function temporaryDirectory() {
	const directory = mkdtempSync(join(tmpdir(), "ao-acp-runtime-test-"));
	temporaryDirectories.push(directory);
	return directory;
}
