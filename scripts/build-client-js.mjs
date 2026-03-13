import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import JavaScriptObfuscator from "javascript-obfuscator";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const staticDir = path.join(rootDir, "static");
const sourceDir = path.join(staticDir, "js");
const distDir = path.join(staticDir, "dist");

const entryNames = ["app", "player", "admin"];

const obfuscationOptions = {
  compact: true,
  controlFlowFlattening: false,
  deadCodeInjection: false,
  debugProtection: false,
  disableConsoleOutput: false,
  identifierNamesGenerator: "hexadecimal",
  numbersToExpressions: true,
  renameGlobals: false,
  selfDefending: false,
  simplify: true,
  splitStrings: true,
  splitStringsChunkLength: 8,
  stringArray: true,
  stringArrayCallsTransform: true,
  stringArrayEncoding: ["base64"],
  stringArrayIndexShift: true,
  stringArrayRotate: true,
  stringArrayShuffle: true,
  stringArrayWrappersCount: 1,
  stringArrayWrappersType: "function",
  transformObjectKeys: true,
  unicodeEscapeSequence: false,
};

fs.mkdirSync(distDir, { recursive: true });

for (const entryName of entryNames) {
  const sourcePath = path.join(sourceDir, `${entryName}.js`);
  if (!fs.existsSync(sourcePath)) {
    console.warn(`Skipping missing source: ${sourcePath}`);
    continue;
  }
  const sourceCode = fs.readFileSync(sourcePath, "utf8");
  const obfuscated = JavaScriptObfuscator.obfuscate(sourceCode, obfuscationOptions).getObfuscatedCode();
  const outputPath = path.join(distDir, `${entryName}.obf.js`);
  fs.writeFileSync(outputPath, obfuscated, "utf8");
  console.log(`Built ${path.relative(rootDir, outputPath)}`);
}
