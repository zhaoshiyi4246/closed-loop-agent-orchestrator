import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const rendererDirectory = path.resolve(process.cwd(), "src/renderer");
const displayAttributes = new Set(["alt", "aria-label", "placeholder", "title"]);

// These are content/data, product names, technical units, or keyboard chords—not
// English UI copy. Keeping this allowlist exact makes newly introduced chrome fail.
const approvedLiterals: Record<string, readonly string[]> = {
	// CLAO's Chinese surface contains product/protocol names and source filenames.
	// Keep exact strings so this does not exempt new English chrome in these files.
	"components/CLAOAcceptance.tsx": ["CLAO ·", "· AO 解析：", "，非单次 provider 请求证明）", "· 用量/费用：unknown"],
	"components/CLAOConnections.tsx": ["为规划、诊断和最终复核配置标准 API。执行任务继续使用原生模型与账号。", "搜索 API 型号", "常用 API 型号", "自定义 API 型号", "· 标准 API 计费", "· 标准 API"],
	"components/CLAODirectives.tsx": ["当前 Worker ·", "原 Worker（不再接收）", "原 Worker 已替换或不再接收。请确认接收对象；不会自动改发 Planner 或新 Worker。"],
	"components/CLAOLegacy.tsx": ["连接 / 更新 API Key", "· 标准 API", "API Key", "迁移旧 CLAO 数据", "default.yaml 的完整路径", "runtime 目录或 state.db 的完整路径"],
	"components/CLAOLocalProject.tsx": ["使用普通目录、空项目或 Git 当前内容；不初始化或提交原目录。"],
	"components/CLAOResults.tsx": ["KB ·", "· exit"],
	"components/CLAORoleForm.tsx": ["局部修复和替换共用上述修复预算；替换先确认旧 Worker 停止，保留旧会话，从冻结来源重新执行。"],
	"components/CLAOSource.tsx": ["KB · 当前磁盘内容", "包含当前未提交修改，在 CLAO 私有工作区执行；不提交或改写原目录。"],
	"components/NewTaskDialog.tsx": ["CLAO 闭环验收"],
	"components/BrowserPanel.tsx": [
		"AO Preview",
		"Demo app preview",
		"The worker exposed a local Vite app with",
		"ao preview",
		"Loaded",
		"$ npm run dev -- --host 127.0.0.1",
		"ready in 418 ms",
		"Local: http://localhost:5173/",
	],
	"components/CenterPane.tsx": ["px"],
	"components/CreateProjectFlow.tsx": ["my-workspace/", "web-app", "main"],
	"components/DaemonStartupLoader.tsx": ["Agent Orchestrator"],
	"components/ProjectSettingsForm.tsx": [
		"main", "ao",
		"No workflow settings for scratch projects.",
		"Tracker intake is not available for scratch projects.",
	],
	"components/SessionInspector.tsx": ["PR #"],
	"components/Sidebar.tsx": ["Agent Orchestrator", "CLAO Native", "daemon"],
	"components/WindowTitlebar.tsx": [
		"Alt+F4",
		"Ctrl+Z",
		"Ctrl+Y",
		"Ctrl+X",
		"Ctrl+C",
		"Ctrl+V",
		"Ctrl+A",
		"Ctrl+R",
		"Ctrl+Shift+I",
		"Ctrl+/",
	],
	"components/settings/ConnectMobileSetup.tsx": ["tailscale ip -4"],
	"components/settings/UpdatesSection.tsx": ["PR #"],
};

// The Chat surface predates this coverage gate and is intentionally being
// localized as a follow-up. Keep the deferral scoped to the new surface so
// hardcoded chrome elsewhere in the renderer still fails this test.
const deferredLocalizationFiles = new Set([
	"components/SessionInterfaceSwitch.tsx",
	"components/chat/ActivityRun.tsx",
	"components/chat/ChatComposer.tsx",
	"components/chat/ChatMarkdown.tsx",
	"components/chat/ChatStatusBanners.tsx",
	"components/chat/ChatTimelineItems.tsx",
	"components/chat/ChatWorkspace.tsx",
	"components/chat/ComposerSuggestMenu.tsx",
	"components/chat/ContextMeter.tsx",
	"components/chat/CopyButton.tsx",
	"components/chat/ElicitationCard.tsx",
	"components/chat/MermaidBlock.tsx",
	"components/chat/SessionChatSurface.tsx",
	"components/chat/TurnPlan.tsx",
	"components/chat/TurnSettingsBar.tsx",
	"components/chat/QueuedMessageDock.tsx",
]);

function rendererFiles(directory: string): string[] {
	return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
		const absolute = path.join(directory, entry.name);
		if (entry.isDirectory()) return rendererFiles(absolute);
		if (!entry.name.endsWith(".tsx") || entry.name.includes(".test.")) return [];
		return [absolute];
	});
}

function normalized(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

function literalBranches(expression: ts.Expression): string[] {
	if (ts.isStringLiteralLike(expression)) return [expression.text];
	if (ts.isTemplateExpression(expression)) {
		return [
			expression.head.text,
			...expression.templateSpans.flatMap((span) => [span.literal.text]),
		];
	}
	if (ts.isConditionalExpression(expression)) {
		return [...literalBranches(expression.whenTrue), ...literalBranches(expression.whenFalse)];
	}
	if (ts.isParenthesizedExpression(expression)) return literalBranches(expression.expression);
	if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.PlusToken) {
		return [...literalBranches(expression.left), ...literalBranches(expression.right)];
	}
	return [];
}

function potentialDisplayText(value: string): boolean {
	return /[A-Za-z]{2}/.test(value);
}

function approved(file: string, value: string): boolean {
	const relative = path.relative(rendererDirectory, file).replace(/\\/g, "/");
	if (deferredLocalizationFiles.has(relative)) return true;
	return approvedLiterals[relative]?.includes(value) ?? false;
}

describe("renderer localization coverage", () => {
	it("does not introduce hardcoded English JSX chrome", () => {
		const violations: string[] = [];
		for (const file of rendererFiles(rendererDirectory)) {
			const source = readFileSync(file, "utf8");
			const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
			const record = (node: ts.Node, rawValue: string) => {
				const value = normalized(rawValue);
				if (!value || !potentialDisplayText(value) || approved(file, value)) return;
				const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
				violations.push(`${path.relative(rendererDirectory, file)}:${line} ${JSON.stringify(value)}`);
			};
			const visit = (node: ts.Node) => {
				if (ts.isJsxText(node)) record(node, node.getText(sourceFile));
				if (ts.isJsxAttribute(node) && displayAttributes.has(node.name.getText(sourceFile)) && node.initializer) {
					if (ts.isStringLiteral(node.initializer)) record(node, node.initializer.text);
					if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
						for (const branch of literalBranches(node.initializer.expression)) record(node, branch);
					}
				}
				ts.forEachChild(node, visit);
			};
			visit(sourceFile);
		}

		expect(violations, violations.join("\n")).toEqual([]);
	});
});
