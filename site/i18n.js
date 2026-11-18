// Page text in English and Korean. Text that comes from the logs (failure
// messages, commands, file names) is shown as it is, never translated.

export const LANGS = { en: "English", ko: "한국어" };

const MESSAGES = {
  en: {
    "status.loading": "Loading Relate WebAssembly…",
    "status.downloading": "Downloading the graph…",
    "status.building": "Building the graph in Relate…",
    "status.ready": "Relate WebAssembly · graph built in {s} s · {calls} calls",
    "status.failed": "Could not start: {msg}",
    "nav.failures": "Failures", "nav.check": "Pre-run check", "nav.evaluation": "Evaluation", "nav.query": "Query",
    "hero.eyebrow": "faildex · built on Relate",
    "hero.title": "Coding agents fail the same way twice. <span>The graph remembers.</span>",
    "hero.lede": "faildex reads Claude Code, Codex and Cursor logs into one Relate graph, finds the failures that keep coming back, and warns the agent before it repeats one. This page rebuilds that graph from 422 public sessions in your browser and runs every query live. Nothing is sent to a server.",
    "result.label": "of failures in later sessions had already happened in an earlier session",
    "result.seen": "{n} seen before", "result.new": "{n} new", "result.of": "of {n} later failures",
    "result.warn": "of those {n} also had a recovery on record ({w})",
    "kpi.sessions": "sessions", "kpi.calls": "tool calls", "kpi.keys": "failure keys", "kpi.rels": "relationships",
    "fail.title": "Failures that came back",
    "fail.intro": "Each failure below hit two or more sessions. The map shows where they cluster; the list shows when each one happened. Select one to see its place in the graph, how sessions got past it, and the log lines behind it.",
    "cypher.show": "Show Cypher", "cypher.hide": "Hide Cypher",
    "map.size": "Tile size: sessions that hit the failure", "map.none": "no recovery on record", "map.fixed": "recovered in an earlier session",
    "list.sessions": "sessions", "tag.recovered": "recovered {n}×", "tag.none": "no recovery",
    "detail.recovered": "recovered {n} of {m} times", "detail.none": "no recovery on record",
    "facts.sessions": "Sessions", "facts.calls": "Failed calls", "facts.first": "First seen", "facts.last": "Last seen",
    "sub.when": "When it happened", "sub.whenHint": "each dot is one failed call",
    "sub.graph": "In the graph", "sub.graphHint": "sessions → command → failure",
    "sub.paths": "How sessions got past it", "sub.pathsHint": "same command working again",
    "sub.evidence": "Evidence", "sub.evidenceHint": "pointers into the public logs; the graph keeps no raw text",
    "paths.none": "No session shows the command working again within five calls. The warning says so: stop and check before retrying.",
    "paths.more": "→ {n} more →",
    "graph.failure": "the failure", "graph.command": "command", "graph.codex": "Codex session", "graph.claude": "Claude Code session",
    "check.title": "Ask before you run",
    "check.intro": "The same lookup the Claude Code hook and the MCP <span class=\"mono\">preflight</span> tool make. A command with a recurring failure gets one line of warning; every other command gets silence.",
    "check.label": "Command the agent is about to run",
    "check.type": "Type a command.",
    "check.noNotice": "no notice",
    "check.silent": "faildex knows no recurring failure for {cmd}, so the hook prints nothing and the agent runs as usual.",
    "check.silentNote": "Looked up as \"{cmd}\". Silence is the common case: most commands get no warning.",
    "check.warnAfter": "The agent also receives the full rule and the log pointers as context. The hook never blocks the command.",
    "check.warnNote": "Looked up as \"{cmd}\": {calls} of its {runs} runs failed this way ({pct}).",
    "check.more": " {n} more known failure(s) go to the agent.",
    "eval.title": "How much was already known",
    "eval.intro": "Sessions of each dataset are ordered by start time: the first 70% are earlier, the rest later. A later failure is recurring when an earlier session already hit it, and warnable when an earlier session also shows the same command working again within five calls.",
    "eval.lRecurring": "recurring: seen in an earlier session", "eval.lWarnable": "warnable: a recovery on record too", "eval.lRest": "the rest",
    "eval.all": "All datasets", "eval.subAll": "{e} earlier · {l} later sessions", "eval.sub": "{name} · {e}/{l} sessions",
    "eval.nums": "<b>{r}</b> of {f} recurring · <b>{p}</b><br><b>{w}</b> warnable · {wp} of recurring",
    "eval.method": "Computed here, in your browser, by Relate WebAssembly. <span class=\"mono\">make eval</span> in the repository computes the same table from the same store.",
    "query.title": "Query the graph",
    "query.intro": "Session, Call, Command and ErrorSig nodes, joined by HAS_CALL, NEXT, RAN and FAILED_WITH. Pick a query or write your own.",
    "query.run": "Run query", "query.took": "{n} rows · {ms} ms", "query.noRows": "No rows.",
    "preset.top": "Most failing commands", "preset.bySessions": "Failures by sessions", "preset.path": "A recovery path", "preset.datasets": "Sessions per dataset",
    "footer.data": "Data:", "footer.source": "Source and reproducible evaluation:",
  },
  ko: {
    "status.loading": "Relate WebAssembly 불러오는 중…",
    "status.downloading": "그래프 데이터 받는 중…",
    "status.building": "Relate에서 그래프를 만드는 중…",
    "status.ready": "Relate WebAssembly · 그래프 생성 {s}초 · 호출 {calls}건",
    "status.failed": "시작하지 못했습니다: {msg}",
    "nav.failures": "실패", "nav.check": "실행 전 확인", "nav.evaluation": "평가", "nav.query": "질의",
    "hero.eyebrow": "faildex · Relate 기반",
    "hero.title": "코딩 에이전트는 같은 실패를 되풀이합니다. <span>그래프는 기억합니다.</span>",
    "hero.lede": "faildex는 Claude Code, Codex, Cursor의 기록을 하나의 Relate 그래프로 모으고, 계속 되풀이되는 실패를 찾아, 에이전트가 같은 실패를 반복하기 전에 경고합니다. 이 페이지는 공개 세션 422개로 그 그래프를 브라우저 안에서 다시 만들고 모든 질의를 직접 실행합니다. 서버로 보내는 데이터는 없습니다.",
    "result.label": "뒤 기간 세션의 실패 중 앞선 세션에서 이미 일어난 비율",
    "result.seen": "이전에 본 실패 {n}건", "result.new": "새 실패 {n}건", "result.of": "뒤 기간 실패 {n}건 중",
    "result.warn": "그 {n}건 중 복구 기록까지 있던 비율 ({w}건)",
    "kpi.sessions": "세션", "kpi.calls": "도구 호출", "kpi.keys": "실패 키", "kpi.rels": "관계",
    "fail.title": "되풀이된 실패",
    "fail.intro": "아래 실패는 모두 두 개 이상의 세션에서 일어났습니다. 지도는 실패가 어디에 몰려 있는지, 목록은 각 실패가 언제 일어났는지 보여 줍니다. 하나를 고르면 그래프 속 위치, 세션들이 어떻게 넘어갔는지, 근거가 된 로그 위치를 볼 수 있습니다.",
    "cypher.show": "Cypher 보기", "cypher.hide": "Cypher 숨기기",
    "map.size": "타일 크기: 그 실패를 겪은 세션 수", "map.none": "복구 기록 없음", "map.fixed": "앞선 세션에서 복구됨",
    "list.sessions": "세션", "tag.recovered": "복구 {n}회", "tag.none": "복구 없음",
    "detail.recovered": "{m}번 중 {n}번 복구", "detail.none": "복구 기록 없음",
    "facts.sessions": "세션", "facts.calls": "실패한 호출", "facts.first": "처음 발생", "facts.last": "마지막 발생",
    "sub.when": "언제 일어났나", "sub.whenHint": "점 하나가 실패한 호출 하나",
    "sub.graph": "그래프 속 위치", "sub.graphHint": "세션 → 명령 → 실패",
    "sub.paths": "세션들이 넘어간 방법", "sub.pathsHint": "같은 명령이 다시 성공한 경로",
    "sub.evidence": "근거", "sub.evidenceHint": "공개 로그 속 위치. 그래프에는 원문을 저장하지 않습니다",
    "paths.none": "다섯 번 안에 같은 명령이 다시 성공한 세션이 없습니다. 그래서 경고는 재시도 전에 멈추고 확인하라고 말합니다.",
    "paths.more": "→ {n}단계 더 →",
    "graph.failure": "실패", "graph.command": "명령", "graph.codex": "Codex 세션", "graph.claude": "Claude Code 세션",
    "check.title": "실행 전에 확인하기",
    "check.intro": "Claude Code 훅과 MCP <span class=\"mono\">preflight</span> 도구가 하는 것과 같은 조회입니다. 되풀이된 실패가 있는 명령에는 한 줄 경고가 붙고, 나머지 명령에는 아무것도 붙지 않습니다.",
    "check.label": "에이전트가 실행하려는 명령",
    "check.type": "명령을 입력하세요.",
    "check.noNotice": "알림 없음",
    "check.silent": "faildex가 아는 {cmd}의 되풀이된 실패가 없어서, 훅은 아무것도 출력하지 않고 에이전트는 평소대로 실행합니다.",
    "check.silentNote": "\"{cmd}\"(으)로 조회했습니다. 대부분의 명령은 경고 없이 지나갑니다.",
    "check.warnAfter": "에이전트는 전체 규칙과 로그 위치도 함께 받습니다. 훅은 명령을 막지 않습니다.",
    "check.warnNote": "\"{cmd}\"(으)로 조회했습니다: 실행 {runs}번 중 {calls}번이 이렇게 실패했습니다({pct}).",
    "check.more": " 알려진 실패 {n}건은 에이전트에게만 전달됩니다.",
    "eval.title": "이미 알려져 있던 비율",
    "eval.intro": "데이터셋마다 세션을 시작 시각 순으로 정렬해 앞의 70%를 앞 기간, 나머지를 뒤 기간으로 나눕니다. 뒤 기간의 실패가 앞 기간 세션에서 이미 일어났으면 '반복', 앞 기간에 같은 명령이 다섯 번 안에 다시 성공한 기록까지 있으면 '경고 가능'으로 셉니다.",
    "eval.lRecurring": "반복: 앞선 세션에서 본 실패", "eval.lWarnable": "경고 가능: 복구 기록도 있음", "eval.lRest": "나머지",
    "eval.all": "전체 데이터셋", "eval.subAll": "앞 기간 {e}개 · 뒤 기간 {l}개 세션", "eval.sub": "{name} · 세션 {e}/{l}",
    "eval.nums": "실패 {f}건 중 반복 <b>{r}</b>건 · <b>{p}</b><br>경고 가능 <b>{w}</b>건 · 반복의 {wp}",
    "eval.method": "이 표는 지금 브라우저 안에서 Relate WebAssembly가 계산했습니다. 저장소의 <span class=\"mono\">make eval</span>도 같은 스토어로 같은 표를 계산합니다.",
    "query.title": "그래프에 질의하기",
    "query.intro": "Session, Call, Command, ErrorSig 노드가 HAS_CALL, NEXT, RAN, FAILED_WITH로 이어져 있습니다. 예시를 고르거나 직접 작성해 보세요.",
    "query.run": "질의 실행", "query.took": "{n}행 · {ms}ms", "query.noRows": "결과가 없습니다.",
    "preset.top": "가장 많이 실패한 명령", "preset.bySessions": "세션 수로 본 실패", "preset.path": "복구 경로", "preset.datasets": "데이터셋별 세션",
    "footer.data": "데이터:", "footer.source": "소스와 재현 가능한 평가:",
  },
};

const STORAGE = "faildex.lang";

function pick() {
  const asked = new URLSearchParams(location.search).get("lang");
  if (asked && MESSAGES[asked]) return asked;
  try {
    const saved = localStorage.getItem(STORAGE);
    if (saved && MESSAGES[saved]) return saved;
  } catch {}
  return (navigator.language || "").toLowerCase().startsWith("ko") ? "ko" : "en";
}

export const lang = pick();

/** The text for `key` in the page language, with {name} filled from `vars`. */
export function t(key, vars = {}) {
  const text = MESSAGES[lang][key] ?? MESSAGES.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

/** Fill every element marked data-i18n (text) or data-i18n-html (trusted markup). */
export function applyStatic(root = document) {
  document.documentElement.lang = lang;
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
}

/** Switch language: remember it and reload, so every number and label is redrawn once. */
export function switchTo(next) {
  try { localStorage.setItem(STORAGE, next); } catch {}
  const url = new URL(location.href);
  url.searchParams.set("lang", next);
  location.href = url.toString();
}
