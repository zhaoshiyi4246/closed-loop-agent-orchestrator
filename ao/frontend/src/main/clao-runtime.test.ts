import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { packagedCoreEnvironment, withPackagedCoreEnvironment } from "./clao-runtime";

describe("installed CLAO acceptance runtime", () => {
	it("fails closed for an incomplete installation and resolves a self-contained install with spaces", () => {
		const root = mkdtempSync(path.join(tmpdir(), "clao installed "));
		try {
			expect(() => packagedCoreEnvironment(root)).toThrow("installation is incomplete");
			for (const file of ["python/python.exe", "python/python-core.exe", "python/python-core._pth", "clao-core/src/loopcore/ao_acceptance.py", "clao-core/src/loopcore/ao_legacy.py"]) {
				mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
				writeFileSync(path.join(root, file), "fixture");
			}
			expect(packagedCoreEnvironment(root)).toEqual({
				CLAO_CORE_PYTHON: path.join(root, "python", "python-core.exe"),
				CLAO_CORE_ROOT: path.join(root, "clao-core"),
				PYTHONDONTWRITEBYTECODE: "1",
			});
			const env = withPackagedCoreEnvironment({ Path: "existing-git", PATH: "existing-codex", CLAO_CORE_PYTHON: "foreign-python" }, root);
			expect(env.Path).toBeUndefined();
			expect(env.PATH).toBe([path.join(root, "python"), "existing-git", "existing-codex"].join(path.delimiter));
			expect(env.CLAO_CORE_PYTHON).toBe(path.join(root, "python", "python-core.exe"));
		} finally { rmSync(root, { recursive: true, force: true }); }
	});
});
