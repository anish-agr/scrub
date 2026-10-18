// Read and write single lines of the repo-root .env (a symlink in a worktree: the real file is written).
// Values are never printed.
import { parse } from "dotenv";
import { existsSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { REPO_DIR } from "../src/config.js";

const FILE = path.join(REPO_DIR, ".env");

export const readEnv = (): Record<string, string> => (existsSync(FILE) ? parse(readFileSync(FILE)) : {});

// Replace only the NAME= line (or append it). Everything else in the file stays byte for byte.
export function setEnv(name: string, value: string, file = FILE) {
  const real = existsSync(file) ? realpathSync(file) : file;
  const text = existsSync(real) ? readFileSync(real, "utf8") : "";
  const lines = text.split("\n");
  const i = lines.findIndex((l) => l.startsWith(`${name}=`));
  if (i >= 0) lines[i] = `${name}=${value}`;
  else lines.splice(lines.at(-1) === "" ? lines.length - 1 : lines.length, 0, `${name}=${value}`);
  writeFileSync(real, lines.join("\n"));
  console.log(`[env] wrote ${name} in .env`);
}
