import { existsSync } from "node:fs";
import path from "node:path";

/** Packaged acceptance always uses the audited, bundled interpreter and core. */
export function packagedCoreEnvironment(resources: string): Record<string, string> {
	const python = path.join(resources, "python", "python-core.exe");
	const core = path.join(resources, "clao-core");
	for (const file of [python, path.join(resources, "python", "python-core._pth"), path.join(resources, "python", "python.exe"), path.join(core, "src", "loopcore", "ao_acceptance.py"), path.join(core, "src", "loopcore", "ao_legacy.py")]) {
		if (!existsSync(file)) throw new Error("CLAO installation is incomplete: bundled acceptance runtime is missing. Reinstall the candidate.");
	}
	return { CLAO_CORE_PYTHON: python, CLAO_CORE_ROOT: core, PYTHONDONTWRITEBYTECODE: "1" };
}

export function withPackagedCoreEnvironment(env: NodeJS.ProcessEnv, resources: string): NodeJS.ProcessEnv {
	const result = { ...env, ...packagedCoreEnvironment(resources) };
	const pathKeys = Object.keys(env).filter((key) => key.toLowerCase() === "path");
	const inheritedPath = pathKeys.map((key) => env[key]).filter(Boolean).join(path.delimiter);
	for (const key of pathKeys) delete result[key];
	result.PATH = [path.join(resources, "python"), inheritedPath].filter(Boolean).join(path.delimiter);
	return result;
}
