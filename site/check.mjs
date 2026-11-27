// Rebuilds the graph in Relate WebAssembly under Node and prints the evaluation
// as JSON, so a test can compare it with what the Python side computes; with commands
// as arguments, also what the demo shows right after each of them fails.
import { readFileSync } from "node:fs";
import { initSync, RelateDb } from "./vendor/relate.js";
import { load, evaluate, notices, run } from "./graph.js";

const here = (name) => new URL(name, import.meta.url);
initSync({ module: readFileSync(here("./vendor/relate_bg.wasm")) });
const data = JSON.parse(readFileSync(here("./data.json"), "utf8"));
const db = new RelateDb();
const calls = load(db, data);
const shown = Object.fromEntries(process.argv.slice(2).map((c) => [c, notices(db, run, c)]));
console.log(JSON.stringify({ calls, scores: evaluate(db, data.sources), notices: shown }));
