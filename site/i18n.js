// Page text in English and Korean. Text that comes from the logs (failure
// messages, commands, file names) is shown as it is, never translated.

export const LANGS = { en: "English", ko: "한국어" };

const MESSAGES = {
  en: {
    "status.loading": "Loading Relate WebAssembly…",
    "status.downloading": "Downloading the graph…",
    "status.building": "Building the graph in Relate…",
    "status.ready": "Relate WebAssembly · {calls} calls",
    "status.readyShort": "{calls} calls",
    "status.failed": "Could not start: {msg}",
    "nav.failures": "1 Failures", "nav.failure": "2 One failure", "nav.check": "3 Warning", "nav.evaluation": "4 Proof", "nav.query": "Query",
    "hero.eyebrow": "faildex · coding agent failure index · 422 public sessions",
    "hero.title": "Coding agents repeat the same failures. <span>faildex warns them before the second try.</span>",
    "hero.lede": "It indexes past Claude Code, Codex, Cursor and Antigravity logs into a Relate graph, finds failures that keep coming back, and prints a one-line warning before the agent runs that command again.",
    "hero.when": "WHEN SHOWN · Right before the agent runs a command that failed in earlier sessions",
    "hero.meta": "{s} public sessions · {c} tool calls · {n} recurring failures",
    "hero.start": "Below: top recurring failures — click any row to see how sessions recovered ↓",
    "s1.title": "The same failures come back",
    "s1.intro": "Each bar is a failure seen in 2+ sessions. Bar length shows how many sessions hit it; color shows whether an earlier session got the same command working again.",
    "s1.take": "<b>{n}</b> failures came back across 422 sessions. #1 is <b>{cmd}</b> (<code>{sig}</code>) in <b>{s} sessions</b> ({c} calls).",
    "s1.more": "Show top {shown} recurring failures (+{rest} more)",
    "s1.less": "Show top {n}",
    "s1.next": "Pick any failure above, or follow the selected one below ↓",
    "s2.title": "Follow one failure through the graph",
    "s2.intro": "Every session that hit this failure points at the same node in the graph, so what one session learned is one hop away from the next.",
    "s2.pick": "Failure",
    "s2.takeFixed": "{s} sessions hit this ({m} failed calls). {n} times the same command worked again within 5 calls (paths in b).",
    "s2.takeNone": "{s} sessions hit this ({m} failed calls), and none shows a way out. The warning says so: no recovery on record.",
    "s2.next": "Next: what the agent sees before it runs <code>{cmd}</code> ↓",
    "s2.nextPlain": "Next: what the agent sees before it runs a command ↓",
    "check.title": "The agent is warned before it repeats it",
    "check.try": "Or try one of these:",
    "s3.next": "Next: was this knowledge really there in advance? ↓",
    "eval.title": "Was it really known in advance?",
    "query.eyebrow": "For the curious",
    "query.title": "Query the graph yourself",
    "result.label": "of failures in later sessions had already happened in an earlier session",
    "result.seen": "{n} seen before", "result.new": "{n} new", "result.of": "of {n} later failures",
    "result.warn": "of those {n} also had a recovery on record ({w})",
    "kpi.sessions": "sessions", "kpi.calls": "tool calls", "kpi.keys": "failure keys", "kpi.rels": "relationships",
    "fail.title": "Failures that came back",
    "fail.intro": "Each failure below hit two or more sessions. Select one to see its place in the graph, how sessions got past it, and the log lines behind it.",
    "cypher.show": "Show Cypher", "cypher.hide": "Hide Cypher",
    "map.size": "Bar length = sessions that hit the failure", "map.none": "Red = no recovery on record yet", "map.fixed": "Green = recovery on record",
    "list.sessions": "sessions", "tag.recovered": "recovery on record ({r}/{c})", "tag.none": "no recovery yet",
    "row.sessions": "{s} sessions", "row.calls": "{c} calls",
    "cmd.unparsedShell": "Unparsed shell block", "cmd.inlineScript": "Inline script", "cmd.plusMore": "+{n} more",
    "detail.recovered": "recovered {n} of {m} calls", "detail.none": "no recovery on record",
    "facts.sessions": "Sessions", "facts.calls": "Failed calls", "facts.first": "First seen", "facts.last": "Last seen",
    "sub.when": "When it happened", "sub.whenHint": "each dot is one failed call",
    "sub.graph": "In the graph", "sub.graphHint": "aggregated sessions → command → failure",
    "sub.paths": "Recovery paths", "sub.pathsHint": "how many calls until the same command worked",
    "sub.evidence": "Evidence", "sub.evidenceHint": "pointers into the public logs; the graph keeps no raw text",
    "paths.none": "No session shows the command working again within five calls, so the warning says: no recovery on record.",
    "paths.more": "→ {n} more →",
    "graph.failure": "Shared failure", "graph.command": "Command or tool", "graph.codex": "Codex", "graph.claude": "Claude Code",
    "graph.colAgents": "Sessions by agent", "graph.colCmds": "Command or tool", "graph.colFailure": "Failure",
    "graph.agentLine": "{s} sessions · {c} calls", "graph.cmdLine": "{s}s · {c} calls",
    "graph.otherCmds": "{n} other commands",
    "graph.unparsedExplain": "Unparsed shell block: a shell_command or Bash call whose inline script or assignment had no single command template.",
    "graph.otherExplain": "Other commands grouped above: {list}.",
    "graph.legendAgent": "{agent} sessions (aggregated)", "graph.legendCmd": "Command or tool run", "graph.legendFail": "Shared failure",
    "check.intro": "The same lookup the Claude Code hook and the MCP <span class=\"mono\">preflight</span> tool make. A command with a recurring failure gets one line of warning; every other command gets silence.",
    "check.label": "Command the agent is about to run",
    "check.type": "Type a command.",
    "check.noNotice": "no notice",
    "check.silent": "faildex knows no recurring failure for {cmd}, so the hook prints nothing and the agent runs as usual.",
    "check.silentNote": "Looked up as \"{cmd}\". Silence is the common case: most commands get no warning.",
    "check.warnAfter": "The agent also receives the full rule and the log pointers as context. The hook never blocks the command.",
    "check.warnNote": "Looked up as <code>{cmd}</code>: <b>{sessions} earlier sessions</b> ({calls} of its {runs} runs, {pct}) failed this way.",
    "check.scopeDiff": "Why the numbers differ: Steps 1–2 counted all commands that hit this failure (<b>{totalS} sessions</b>, {totalC} calls). Here the pre-run warning counts only <code>{cmd}</code>: <b>{cmdS} sessions</b> ({cmdC} of {runs} runs, {pct}).",
    "check.scopeSame": "Same scope as Steps 1–2: only <code>{cmd}</code> hit this failure (<b>{cmdS} sessions</b>, {cmdC} of {runs} runs, {pct}).",
    "check.scopeOther": "Top warning for <code>{cmd}</code> is <code>{sig}</code>: <b>{cmdS} sessions</b> ({cmdC} of {runs} runs, {pct}).",
    "check.scopeOtherDiff": "Top warning for <code>{cmd}</code> is <code>{sig}</code>: <b>{cmdS} sessions</b> ({cmdC} of {runs} runs, {pct}) on <code>{cmd}</code> alone, vs. <b>{totalS} sessions</b> ({totalC} calls) across all commands.",
    "check.more": " {n} more known failure(s) go to the agent.",
    "eval.intro": "Sessions of each dataset are ordered by start time: the first 70% are earlier, the rest later. A later failure is recurring when an earlier session already hit it, and has a recovery on record when an earlier session also shows the same command working again within five calls.",
    "eval.lRecurring": "recurring: seen in an earlier session", "eval.lWarnable": "recovery also recorded", "eval.lRest": "the rest",
    "eval.all": "All datasets", "eval.subAll": "{e} earlier · {l} later sessions", "eval.sub": "{name} · {e}/{l} sessions",
    "eval.nums": "<b>{r}</b> of {f} recurring · <b>{p}</b><br><b>{w}</b> of those with a recovery on record · {wp}",
    "eval.method": "Computed here, in your browser, by Relate WebAssembly. <span class=\"mono\">make eval</span> in the repository computes the same table from the same store.",
    "query.intro": "Session, Call, Command and ErrorSig nodes, joined by HAS_CALL, NEXT, RAN and FAILED_WITH. Pick a query or write your own.",
    "query.run": "Run query", "query.took": "{n} rows · {ms} ms", "query.noRows": "No rows.",
    "preset.top": "Most failing commands", "preset.bySessions": "Failures by sessions", "preset.path": "A recovery path", "preset.datasets": "Sessions per dataset",
    "footer.data": "Data:", "footer.source": "Source and reproducible evaluation:",
    "hero.mini": "The agent receives this warning and past fixes in context — the command runs without blocking.",
    "sub.whenSum": "{a} – {b} · {n} failed calls",
    "graph.hSessions": "{n} sessions",
    "graph.aria": "Aggregated graph from {n} sessions, through commands/tools, to this failure",
    "result.caveat": "How often a later failure had already happened before. It is not a measured effect of the warning.",
    "check.scope": " Step 2 counted every command that hit this failure; here only {cmd}'s own runs count.",
    "graph.more": "+{n} more",
  },
  ko: {
    "status.loading": "Relate WebAssembly 불러오는 중…",
    "status.downloading": "그래프 데이터 받는 중…",
    "status.building": "Relate에서 그래프를 만드는 중…",
    "status.ready": "Relate WebAssembly · 호출 {calls}건",
    "status.readyShort": "호출 {calls}건",
    "status.failed": "시작하지 못했습니다: {msg}",
    "nav.failures": "1 실패", "nav.failure": "2 실패 하나", "nav.check": "3 경고", "nav.evaluation": "4 증명", "nav.query": "질의",
    "hero.eyebrow": "faildex · 코딩 에이전트 실패 색인 · 공개 세션 422개",
    "hero.title": "코딩 에이전트는 같은 실패를 되풀이합니다. <span>faildex는 다시 실행하기 전에 경고합니다.</span>",
    "hero.lede": "Claude Code, Codex, Cursor, Antigravity의 과거 실행 기록을 Relate 그래프로 모아 여러 세션에서 반복된 실패를 찾고, 같은 명령을 실행하기 직전에 한 줄 경고를 띄웁니다.",
    "hero.when": "언제 뜨나 · 에이전트가 이전 세션에서 자주 실패한 명령을 실행하기 직전에 표시",
    "hero.meta": "공개 세션 {s}개 · 도구 호출 {c}건 · 반복 실패 {n}개",
    "hero.start": "아래 보기: 반복 실패 목록에서 항목을 누르면 복구 경로와 근거를 따라갑니다 ↓",
    "s1.title": "같은 실패가 되풀이됩니다",
    "s1.intro": "막대 하나가 두 개 이상의 세션에서 반복된 실패입니다. 막대가 길수록 더 많은 세션이 겪었고, 색은 같은 명령이 곧 다시 성공한 기록이 있는지를 뜻합니다.",
    "s1.take": "세션 422개에서 반복 실패 <b>{n}개</b>를 찾았습니다. 1위는 <b>{cmd}</b>의 <code>{sig}</code>로, <b>세션 {s}개</b>({c}회 호출)에서 발생했습니다.",
    "s1.more": "상위 {shown}개까지 보기 (+{rest}개)",
    "s1.less": "상위 {n}개만 보기",
    "s1.next": "위에서 실패를 고르거나, 선택된 항목을 아래에서 자세히 보세요 ↓",
    "s2.title": "실패 하나를 그래프로 따라가기",
    "s2.intro": "이 실패를 겪은 모든 세션이 그래프의 같은 노드를 가리킵니다. 그래서 한 세션이 배운 것이 다음 세션과 한 걸음 거리에 있습니다.",
    "s2.pick": "실패",
    "s2.takeFixed": "세션 {s}개가 겪었습니다(실패 {m}건). 그중 {n}번은 5호출 안에 같은 명령이 다시 성공했고, 경로는 b에 있습니다.",
    "s2.takeNone": "세션 {s}개가 겪었고(실패 {m}건), 넘어간 기록은 없습니다. 경고도 그대로 알립니다: 복구 기록 없음.",
    "s2.next": "다음: 에이전트가 <code>{cmd}</code>를 실행하기 전에 보는 것 ↓",
    "s2.nextPlain": "다음: 에이전트가 명령을 실행하기 전에 보는 것 ↓",
    "check.title": "에이전트는 반복하기 전에 경고를 받습니다",
    "check.try": "아래 명령도 눌러 보세요:",
    "s3.next": "다음: 이 지식이 정말 미리 있었을까? ↓",
    "eval.title": "정말 미리 알 수 있었을까?",
    "query.eyebrow": "더 알고 싶다면",
    "query.title": "그래프에 직접 질의하기",
    "result.label": "이후 30% 세션의 실패 중, 이전 70% 세션에서 이미 일어났던 비율",
    "result.seen": "이전에 본 실패 {n}건", "result.new": "새 실패 {n}건", "result.of": "이후 실패 {n}건 중",
    "result.warn": "그 {n}건 중 복구 기록까지 있던 비율 ({w}건)",
    "kpi.sessions": "세션", "kpi.calls": "도구 호출", "kpi.keys": "실패 키", "kpi.rels": "관계",
    "fail.title": "되풀이된 실패",
    "fail.intro": "아래 실패는 모두 두 개 이상의 세션에서 일어났습니다. 하나를 고르면 그래프 속 위치, 세션들이 어떻게 넘어갔는지, 근거가 된 로그 위치를 볼 수 있습니다.",
    "cypher.show": "Cypher 보기", "cypher.hide": "Cypher 숨기기",
    "map.size": "막대 길이 = 그 실패를 겪은 세션 수", "map.none": "빨강 = 아직 복구 기록 없음", "map.fixed": "초록 = 복구 기록 있음",
    "list.sessions": "세션", "tag.recovered": "복구 기록 있음 ({r}/{c}건)", "tag.none": "복구 기록 없음",
    "row.sessions": "세션 {s}개", "row.calls": "{c}건",
    "cmd.unparsedShell": "단일 명령 없는 셸 블록", "cmd.inlineScript": "인라인 스크립트", "cmd.plusMore": "외 {n}개",
    "detail.recovered": "{m}번 중 {n}번 복구", "detail.none": "복구 기록 없음",
    "facts.sessions": "세션", "facts.calls": "실패한 호출", "facts.first": "처음 발생", "facts.last": "마지막 발생",
    "sub.when": "언제 일어났나", "sub.whenHint": "점 하나가 실패한 호출 하나",
    "sub.graph": "그래프 속 위치", "sub.graphHint": "세션(합산) → 명령 → 실패",
    "sub.paths": "복구 경로", "sub.pathsHint": "같은 명령이 다시 성공하기까지 걸린 호출 수",
    "sub.evidence": "근거", "sub.evidenceHint": "공개 로그 속 위치. 그래프에는 원문을 저장하지 않습니다",
    "paths.none": "다섯 번 안에 같은 명령이 다시 성공한 세션이 없어서, 경고에도 '복구 기록 없음'으로 표시됩니다.",
    "paths.more": "→ {n}단계 더 →",
    "graph.failure": "공유된 실패", "graph.command": "명령 또는 도구", "graph.codex": "Codex", "graph.claude": "Claude Code",
    "graph.colAgents": "에이전트별 세션", "graph.colCmds": "실행한 명령·도구", "graph.colFailure": "실패",
    "graph.agentLine": "세션 {s}개 · {c}건", "graph.cmdLine": "세션 {s} · {c}건",
    "graph.otherCmds": "그 외 명령 {n}개",
    "graph.unparsedExplain": "단일 명령 없는 셸 블록: 변수 대입이나 여러 줄 스크립트여서 하나의 명령어로 묶이지 않은 shell_command/Bash 호출입니다.",
    "graph.otherExplain": "위에 묶인 그 외 명령: {list}.",
    "graph.legendAgent": "{agent} 세션 (합산)", "graph.legendCmd": "실패한 명령 또는 도구", "graph.legendFail": "공유된 실패 키",
    "check.intro": "Claude Code 훅과 MCP <span class=\"mono\">preflight</span> 도구가 하는 것과 같은 조회입니다. 되풀이된 실패가 있는 명령에는 한 줄 경고가 붙고, 나머지 명령에는 아무것도 붙지 않습니다.",
    "check.label": "에이전트가 실행하려는 명령",
    "check.type": "명령을 입력하세요.",
    "check.noNotice": "알림 없음",
    "check.silent": "faildex가 아는 {cmd}의 되풀이된 실패가 없어서, 훅은 아무것도 출력하지 않고 에이전트는 평소대로 실행합니다.",
    "check.silentNote": "\"{cmd}\"(으)로 조회했습니다. 대부분의 명령은 경고 없이 지나갑니다.",
    "check.warnAfter": "에이전트는 전체 규칙과 로그 위치도 함께 받습니다. 훅은 명령을 막지 않습니다.",
    "check.warnNote": "<code>{cmd}</code> 조회 결과: <b>{sessions}개 이전 세션</b>({runs}회 실행 중 {calls}회, {pct})에서 이렇게 실패했습니다.",
    "check.scopeDiff": "숫자가 다른 이유: 1·2단계는 이 실패를 겪은 모든 명령을 합쳐 <b>{totalS}개 세션</b>({totalC}건)으로 셌습니다. 반면 3단계의 실행 전 경고는 <code>{cmd}</code> 실행만 따로 세어 <b>{cmdS}개 세션</b>({runs}회 중 {cmdC}회, {pct})을 표시합니다.",
    "check.scopeSame": "1·2단계와 같은 범위입니다: 이 실패는 <code>{cmd}</code>에서만 일어나 <b>{cmdS}개 세션</b>({runs}회 중 {cmdC}회, {pct})으로 일치합니다.",
    "check.scopeOther": "<code>{cmd}</code>의 최우선 경고는 <code>{sig}</code>입니다: <b>{cmdS}개 세션</b>({runs}회 중 {cmdC}회, {pct}).",
    "check.scopeOtherDiff": "<code>{cmd}</code>의 최우선 경고는 <code>{sig}</code>입니다: <code>{cmd}</code>만 세면 <b>{cmdS}개 세션</b>({runs}회 중 {cmdC}회, {pct}), 전체 명령 합산 시 <b>{totalS}개 세션</b>({totalC}건)입니다.",
    "check.more": " 알려진 실패 {n}건은 에이전트에게만 전달됩니다.",
    "eval.intro": "데이터셋마다 세션을 시작 시각 순으로 정렬해 이전 70%와 이후 30%로 나눕니다. 이후 세션의 실패가 이전 세션에서 이미 일어났으면 '반복', 이전 세션에 같은 명령이 다섯 번 안에 다시 성공한 기록까지 있으면 '복구 기록 있음'으로 셉니다.",
    "eval.lRecurring": "반복: 이전 세션에서 본 실패", "eval.lWarnable": "복구 기록도 있음", "eval.lRest": "나머지",
    "eval.all": "전체 데이터셋", "eval.subAll": "이전 {e}개 · 이후 {l}개 세션", "eval.sub": "{name} · 세션 {e}/{l}",
    "eval.nums": "실패 {f}건 중 반복 <b>{r}</b>건 · <b>{p}</b><br>그중 복구 기록 있음 <b>{w}</b>건 · {wp}",
    "eval.method": "이 표는 지금 브라우저 안에서 Relate WebAssembly가 계산했습니다. 저장소의 <span class=\"mono\">make eval</span>도 같은 스토어로 같은 표를 계산합니다.",
    "query.intro": "Session, Call, Command, ErrorSig 노드가 HAS_CALL, NEXT, RAN, FAILED_WITH로 이어져 있습니다. 예시를 고르거나 직접 작성해 보세요.",
    "query.run": "질의 실행", "query.took": "{n}행 · {ms}ms", "query.noRows": "결과가 없습니다.",
    "preset.top": "가장 많이 실패한 명령", "preset.bySessions": "세션 수로 본 실패", "preset.path": "복구 경로", "preset.datasets": "데이터셋별 세션",
    "footer.data": "데이터:", "footer.source": "소스와 재현 가능한 평가:",
    "hero.mini": "에이전트는 이 경고와 과거 해결 기록을 함께 받으며, 명령 실행을 막지는 않습니다.",
    "sub.whenSum": "{a} – {b} · 실패한 호출 {n}건",
    "graph.hSessions": "세션 {n}개",
    "graph.aria": "세션 {n}개를 에이전트별로 모아 명령/도구, 공유된 실패로 연결한 그래프",
    "result.caveat": "이후 실패가 이전에 이미 일어났던 비율입니다. 경고의 예방 효과를 측정한 수치는 아닙니다.",
    "check.scope": " 2단계는 이 실패를 겪은 모든 명령을 셌고, 여기서는 {cmd}의 실행만 셉니다.",
    "graph.more": "외 {n}개",
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
