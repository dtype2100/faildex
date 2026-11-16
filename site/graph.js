// Rebuilds the faildex graph inside Relate (WebAssembly) and exposes the same
// queries the Python side runs. Used by index.html and by the Node check.

export const KEYS = { Session: "id", Call: "id", Command: "template", ErrorSig: "sig", Source: "name" };
export const RECOVERY_HOPS = 5;
// A failure must be at least this share of a command's runs to be worth a warning.
export const MIN_RATE = 0.03;
const BATCH = 2000;

export const Q = {
  counts: `MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n ORDER BY label`,
  relationships: `MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS n ORDER BY type`,
  recurring: `MATCH (e:ErrorSig)<-[:FAILED_WITH]-(f:Call)<-[:HAS_CALL]-(s:Session)
OPTIONAL MATCH (f)-[:RAN]->(k:Command)
WITH e, count(DISTINCT s) AS sessions, count(f) AS calls, collect(DISTINCT k.template)[0..3] AS commands
WHERE sessions >= 2
RETURN e.sig AS failure, sessions, calls, commands
ORDER BY sessions DESC, calls DESC LIMIT 15`,
  recovery: `MATCH (e:ErrorSig {sig: $failure})<-[:FAILED_WITH]-(f:Call)-[:RAN]->(k:Command)
WHERE coalesce(f.compound, false) = false
MATCH p = (f)-[:NEXT*1..${RECOVERY_HOPS}]->(g:Call {ok: true}), (g)-[:RAN]->(k)
WHERE coalesce(g.compound, false) = false AND (f.ts IS NULL OR g.ts IS NULL OR g.ts >= f.ts)
WITH f, k, min(length(p)) AS hops
MATCH q = (f)-[:NEXT*1..${RECOVERY_HOPS}]->(:Call {ok: true}) WHERE length(q) = hops
WITH f, k, hops, nodes(q)[1] AS step
OPTIONAL MATCH (step)-[:RAN]->(sk:Command)
RETURN k.template AS command, hops AS calls_until_it_worked,
       coalesce(sk.template, step.tool) AS first_step_after_failure, count(DISTINCT f) AS times
ORDER BY times DESC LIMIT 10`,
  evidence: `MATCH (e:ErrorSig {sig: $failure})<-[:FAILED_WITH]-(f:Call)<-[:HAS_CALL]-(s:Session)-[:FROM]->(d:Source)
RETURN d.name AS dataset, s.agent AS agent, s.id AS session, f.source_path AS file, f.source_line AS line
ORDER BY session LIMIT 12`,
  preflight: `MATCH (k:Command {template: $command})<-[:RAN]-(c:Call)
WITH k, count(c) AS runs
MATCH (k)<-[:RAN]-(f:Call)-[:FAILED_WITH]->(e:ErrorSig), (f)<-[:HAS_CALL]-(s:Session)
WITH e, runs, count(DISTINCT s) AS sessions, count(f) AS calls
WHERE sessions >= 2 AND 1.0 * calls / runs >= ${MIN_RATE}
RETURN e.sig AS known_failure, sessions, calls, runs ORDER BY sessions DESC LIMIT 5`,
  commandsWithFailures: `MATCH (k:Command)<-[:RAN]-(c:Call)
WITH k, count(c) AS runs
MATCH (k)<-[:RAN]-(f:Call)-[:FAILED_WITH]->(e:ErrorSig), (f)<-[:HAS_CALL]-(s:Session)
WITH k, e, runs, count(DISTINCT s) AS sessions, count(f) AS calls
WHERE sessions >= 2 AND 1.0 * calls / runs >= ${MIN_RATE}
RETURN DISTINCT k.template AS command ORDER BY command`,
  sessionsOf: `MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)
WHERE s.started_at IS NOT NULL
RETURN s.id AS id, s.started_at AS started ORDER BY started, id`,
  later: `MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $later
OPTIONAL MATCH (c)-[:RAN]->(k:Command)
RETURN c.id AS call, e.sig AS sig, k.template AS command, coalesce(c.compound, false) AS compound`,
  earlierKeys: `MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $earlier AND c.ts < $cut
RETURN DISTINCT e.sig AS sig`,
  recovered: `MATCH (s:Session)-[:HAS_CALL]->(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $earlier AND f.ts < $cut AND coalesce(f.compound, false) = false
MATCH (f)-[:RAN]->(k:Command)<-[:RAN]-(g:Call {ok: true})
WHERE g.ts < $cut AND g.ts >= f.ts AND coalesce(g.compound, false) = false
MATCH (f)-[:NEXT*1..${RECOVERY_HOPS}]->(g)
RETURN DISTINCT e.sig AS sig, k.template AS command`,
};

export function run(db, query, params) {
  const result = JSON.parse(db.execute(query, params ? JSON.stringify(params) : null));
  if (result.error) throw new Error(result.error);
  // Rows come back with sorted keys; put them in the order of the RETURN clause.
  return result.rows.map((row) => Object.fromEntries(result.columns.map((c) => [c, row[c]])));
}

function batches(db, query, rows) {
  for (let i = 0; i < rows.length; i += BATCH) run(db, query, { rows: rows.slice(i, i + BATCH) });
}

// Loads the exported data. onProgress(done, total) is called between batches.
export function load(db, data, onProgress = () => {}) {
  for (const [label, key] of Object.entries(KEYS)) {
    run(db, `CREATE CONSTRAINT ${label.toLowerCase()}_${key} IF NOT EXISTS FOR (n:${label}) REQUIRE n.${key} IS UNIQUE`);
  }
  const str = (i) => data.strings[i];
  batches(db, `UNWIND $rows AS row CREATE (:Source {name: row.name, repo: row.repo, revision: row.revision, license: row.license, url: row.url})`, data.sources);
  batches(db, `UNWIND $rows AS row CREATE (:Session {id: row.id, agent: row.agent, started_at: row.started_at})`, data.sessions);
  batches(db, `UNWIND $rows AS row MATCH (s:Session {id: row.id}), (d:Source {name: row.source}) CREATE (s)-[:FROM]->(d)`,
    data.sessions.filter((s) => s.source));

  const calls = data.calls.map(([session, seq, tool, ok, ts, compound, path, line, command, failure, kind]) => {
    const sid = data.sessions[session].id;
    return { id: `${sid}:${seq}`, session: sid, seq, tool: str(tool), ok: ok === 1, ts, compound: compound === 1,
             path: str(path), line, command: str(command), failure: str(failure), kind: str(kind) };
  });
  const commands = [...new Set(calls.map((c) => c.command).filter(Boolean))].map((template) => ({ template }));
  const failures = new Map();
  for (const c of calls) if (c.failure) failures.set(c.failure, c.kind);
  batches(db, `UNWIND $rows AS row CREATE (:Command {template: row.template})`, commands);
  batches(db, `UNWIND $rows AS row CREATE (:ErrorSig {sig: row.sig, kind: row.kind})`,
    [...failures].map(([sig, kind]) => ({ sig, kind })));

  const steps = [
    [`UNWIND $rows AS row MATCH (s:Session {id: row.session})
CREATE (s)-[:HAS_CALL]->(:Call {id: row.id, seq: row.seq, tool: row.tool, ok: row.ok, ts: row.ts,
  compound: row.compound, source_path: row.path, source_line: row.line})`, calls],
    [`UNWIND $rows AS row MATCH (c:Call {id: row.id}), (k:Command {template: row.command}) CREATE (c)-[:RAN]->(k)`,
      calls.filter((c) => c.command)],
    [`UNWIND $rows AS row MATCH (c:Call {id: row.id}), (e:ErrorSig {sig: row.failure}) CREATE (c)-[:FAILED_WITH]->(e)`,
      calls.filter((c) => c.failure)],
    [`UNWIND $rows AS row MATCH (a:Call {id: row.prev}), (b:Call {id: row.next}) CREATE (a)-[:NEXT]->(b)`,
      calls.slice(1).flatMap((c, i) => (calls[i].session === c.session ? [{ prev: calls[i].id, next: c.id }] : []))],
  ];
  const total = steps.reduce((n, [, rows]) => n + rows.length, 0);
  let done = 0;
  for (const [query, rows] of steps) {
    for (let i = 0; i < rows.length; i += BATCH) {
      run(db, query, { rows: rows.slice(i, i + BATCH) });
      done += Math.min(BATCH, rows.length - i);
      onProgress(done, total);
    }
  }
  return calls.length;
}

// The evaluation of docs/evaluation.md, recomputed here: first 70% of each
// dataset's sessions are "earlier", the rest "later".
export function evaluate(db, sources) {
  const out = [];
  for (const { name } of sources) {
    const sessions = run(db, Q.sessionsOf, { source: name });
    const index = Math.floor(sessions.length * 0.7);
    if (index <= 0 || index >= sessions.length) continue;
    const earlier = sessions.slice(0, index).map((s) => s.id);
    const later = sessions.slice(index).map((s) => s.id);
    const cut = sessions[index].started;
    const known = new Set(run(db, Q.earlierKeys, { earlier, cut }).map((r) => r.sig));
    const fixed = new Set(run(db, Q.recovered, { earlier, cut }).map((r) => `${r.sig}\u0000${r.command}`));
    const failures = run(db, Q.later, { later });
    const recurring = failures.filter((f) => known.has(f.sig));
    out.push({
      dataset: name, earlier: earlier.length, later: later.length, failures: failures.length,
      recurring: recurring.length,
      warnable: recurring.filter((f) => !f.compound && fixed.has(`${f.sig}\u0000${f.command}`)).length,
    });
  }
  const sum = (key) => out.reduce((n, r) => n + r[key], 0);
  out.push({ dataset: "all", earlier: sum("earlier"), later: sum("later"), failures: sum("failures"),
             recurring: sum("recurring"), warnable: sum("warnable") });
  return out;
}
