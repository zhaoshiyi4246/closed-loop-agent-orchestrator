import os from "node:os";
import path from "node:path";

// This fork never discovers or attaches to the installed AO application's data.
// Native coding-tool authentication remains owned by the tools themselves.
export const CLAO_NATIVE_NAME = "CLAO Native";
export const CLAO_NATIVE_APP_ID = "dev.clao.native.desktop";
export const CLAO_NATIVE_HOME = path.resolve(process.env.CLAO_NATIVE_HOME || path.join(os.homedir(), ".clao-ao"));
const officialHome = path.join(os.homedir(), ".ao");
const relative = path.relative(officialHome, CLAO_NATIVE_HOME);
if (!relative || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative))) {
	throw new Error("CLAO_NATIVE_HOME must be outside the official AO data directory");
}
export const CLAO_UPDATES_ENABLED = false;
process.env.AO_DATA_DIR = path.join(CLAO_NATIVE_HOME, "data");
process.env.AO_RUN_FILE = path.join(CLAO_NATIVE_HOME, "running.json");
process.env.AO_DEV_ELECTRON_DIR = path.join(CLAO_NATIVE_HOME, "electron");
process.env.AO_PORT = process.env.CLAO_NATIVE_PORT || "7312";
process.env.AO_TELEMETRY_EVENTS = "off";
process.env.AO_TELEMETRY_REMOTE = "off";
process.env.AO_SENTRY_DSN = "";

// A parent shell must not redirect this fork to the installed AO executable.
delete process.env.AO_DAEMON_COMMAND;
