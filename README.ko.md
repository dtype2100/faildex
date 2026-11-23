# faildex

[English](README.md) · **한국어**

코딩 에이전트를 위한 실패 색인입니다. faildex는 Claude Code, Codex, Cursor,
Antigravity의 세션 기록을 하나의 내장형 [Relate](https://github.com/relatedb/relate)
그래프로 모으고, 세션을 넘어 계속 되풀이되는 실패를 찾아, 그래프에서 해결 방법을
읽어 낸 뒤, 에이전트가 같은 명령을 다시 실행하기 전에 알려 줍니다.

Relate by Neo4j 해커톤 출품작입니다.

```bash
curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh   # macOS, Linux
faildex demo
```

Windows는 [설치](#설치)의 PowerShell 한 줄을 쓰세요.

![faildex 브라우저 데모: 뒤 기간 실패의 68.4%가 앞선 세션에서 이미 일어났다는 결과와, 되풀이된 실패를 세션 수 크기와 복구 기록 여부 색으로 보여 주는 실패 지도](docs/images/overview.jpg)

*브라우저 데모는 공개 세션 422개로 그래프를 Relate WebAssembly 안에서 다시 만들고
화면의 모든 수치를 다시 계산합니다. <https://dtype2100.github.io/faildex/>에서 바로 열거나,
로컬에서 `make site && make serve`로 실행합니다.*

## 무엇을 해결하나

코딩 에이전트는 기억하지 못합니다. 한 세션이 `fatal: not a git repository`를 만나
이유를 알아내도, 다음 세션은 같은 실패를 또 만납니다. 에이전트마다 기록 형식이
달라서 세션 사이에도, 에이전트 사이에도 아무것도 이어지지 않습니다.

이 저장소에 들어 있는 공개 세션 기록에서 **뒤 기간 세션의 실패 중 68%는 앞선 세션에서
이미 일어난 실패**였고, 그중 60%는 앞선 세션에 같은 명령이 몇 번 뒤에 다시 성공한
기록까지 있었습니다. 에이전트가 디스크에 갖고 있으면서도 쓰지 못한 지식입니다.

faildex는 이것을 다음 도구로 바꿉니다.

| 실행 | 얻는 것 |
|---|---|
| `faildex rules` | 세션을 넘어 되풀이된 실패에 대한 규칙 제안. 각 제안에는 기록된 복구 방법과 로그 위치가 붙습니다. 승인한 것만 규칙 파일에 기록됩니다. |
| `faildex hook` | Claude Code `PreToolUse` 훅. 되풀이된 실패가 알려진 명령을 실행하기 전에 세션에 한 줄 알림을 띄우고, Claude에게 앞선 세션이 배운 내용을 전달합니다. 그 실패가 해당 명령 실행의 3% 이상이거나(명령을 합쳐 묶은 `zsh` `no matches found` 글롭 실패는 `min_sessions` 세션 이상에서 반복되고 명령줄에 따옴표 없는 글롭이 있을 때) 말하고, 그 밖에는 아무것도 출력하지 않습니다. |
| `faildex mcp` | MCP 도구 `preflight`, `evidence`, `recurring`. 어떤 MCP 에이전트든 실행 전에 물어볼 수 있습니다. |
| `faildex eval` | 위 수치를 저장소의 스토어로 다시 계산합니다. |
| `faildex ingest` | 내 Claude Code, Codex CLI, Cursor, Antigravity 기록을 내 컴퓨터의 개인 스토어(`~/.faildex/store`)에 적재합니다. 위의 모든 명령이 이 스토어를 씁니다. |
| `faildex report` | 내 스토어에서 날짜 전후의 건수를 셉니다: 호출, 실패, 고른 실패 하나, 훅이 보낸 경고. |

### 실제 Claude Code 세션에서

에이전트가 저장소가 아닌 폴더에서 `git status`를 실행합니다. 결과가 나오기 전에
faildex 훅이 앞선 세션들이 배운 것을 보여 주고, Claude가 그에 따라 행동합니다.

![Claude Code 세션: Bash(git status) 아래에 "PreToolUse:Bash says: faildex: `git status` failed with `fatal: not a git repository` in 24 earlier sessions; no recovery on record" 줄이 뜨고, Claude가 "A faildex hook in this project flagged that this same failure has come up in 24 earlier sessions, so I didn't retry."라고 답하는 화면](docs/images/claude-code-hook.jpg)

### 실패 하나를 그래프로 따라가기

브라우저 데모에서 실패를 고르면 언제 일어났는지, 그래프 속 이웃(그 실패를 겪은
세션과 명령), 세션들이 어떻게 넘어갔는지, 근거가 된 로그 위치를 볼 수 있습니다.

<img src="docs/images/failure-detail.jpg" width="640" alt="실패 'rg: regex parse error'의 상세: 세션 8개, 실패한 호출 12건, 발생 타임라인, 그래프 속 이웃, rg가 실패한 뒤 다음 호출에서 성공한 복구 경로(8회)">

## Relate를 어떻게 쓰나

세션 하나의 기록은 목록입니다. "이 실패가 전에도 있었나, 무엇으로 넘어갔나?"는
여러 목록을 가로지르는 경로의 질문이라서 데이터를 그래프에 둡니다.

```
(Source)<-[:FROM]-(Session)-[:HAS_CALL]->(Call)-[:NEXT]->(Call)
                                          |  \
                                       [:RAN] [:FAILED_WITH]
                                          v        v
                                      (Command) (ErrorSig)
```

`Command`와 `ErrorSig` 노드는 모든 세션과 모든 에이전트가 공유합니다. 한 번 본
실패는 같은 실패를 겪은 다른 모든 세션과 한 단계 거리에 있고, 그 세션이 회복한
방법과는 짧은 `NEXT` 경로로 이어집니다.

```cypher
MATCH (k:Command {template: $command})<-[:RAN]-(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
MATCH p = (f)-[:NEXT*1..5]->(g:Call {ok: true}), (g)-[:RAN]->(k)
RETURN e.sig, min(length(p)) AS calls_until_it_worked
```

Relate를 쓰는 곳:

- **내장형 디렉터리 스토어.** `store/`는 이 저장소에 커밋된 Relate 데이터베이스입니다.
  띄울 서버가 없고, `relate.connect("store", read_only=True)`가 설정의 전부입니다.
- **가변 길이 경로를 쓰는 Cypher**로 복구 경로를 찾고, 키가 있는 노드에 `MERGE`를 써서
  같은 기록을 두 번 적재해도 바뀌지 않습니다.
- **모든 키에 유일 제약.** 키 색인 역할도 해서, 호출 4,000건 적재가 제약이 있으면 0.6초,
  없으면 60초 걸립니다.
- **쓰는 쪽 하나, 읽는 쪽 여럿.** 적재가 쓰는 동안 훅과 MCP 서버는 스토어를 읽기 전용으로 엽니다.
- **모든 화면이 쓰는 질의 계층 하나.** `faildex rules`, 훅, MCP 도구가
  [`insight.py`](src/faildex/insight.py)의 같은 함수를 불러서 서로 다른 답을 낼 수 없습니다.

스키마는 [docs/schema.md](docs/schema.md)에 있습니다. 그래프는 명령이나 출력의 원문을
저장하지 않습니다. 명령은 틀(`git push`)로, 실패는 가린 서명으로 바뀌고, 호출마다
로그 줄의 위치만 남깁니다.

## 설치와 실행

### 설치

| | 한 줄 설치 | 필요한 것 |
|---|---|---|
| macOS | `curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh \| sh` | 터미널, git(Xcode 명령줄 도구) |
| Linux | `curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh \| sh` | curl과 git이 있는 셸 |
| Windows | `powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/dtype2100/faildex/main/install.ps1 \| iex"` | PowerShell. git은 필요 없음 |

각 스크립트는 [uv](https://docs.astral.sh/uv/)가 없으면 먼저 설치하고, 이어서 `faildex`
명령을 설치합니다. 다른 것은 바꾸지 않습니다. 먼저 읽어 보고 싶다면
[install.sh](install.sh)와 [install.ps1](install.ps1)를 보세요. 각각 30줄 정도입니다.
uv가 이미 있다면 직접 이렇게 해도 됩니다.

```bash
uv tool install git+https://github.com/dtype2100/faildex      # macOS, Linux
uv tool install https://github.com/dtype2100/faildex/archive/refs/heads/main.zip   # Windows, git 없이
```

설치 후 새 터미널을 열어야 `faildex`가 PATH에 잡힙니다. 그다음 어느 폴더에서든:

```bash
faildex demo                  # 공개 기록으로 규칙 제안, 실행 전 경고, 수치를 보여 줌
faildex check "git status"    # 이 명령에 알려진 실패가 있는지
```

CI에서 macOS, Linux, Windows 모두 설치하고 실행합니다. Windows에서 심볼릭 링크를 만들 수
없으면 `faildex link`는 규칙 파일을 Antigravity 플러그인에 복사합니다. 규칙을 새로 승인한
뒤 다시 실행하세요.

`faildex demo`는 다운로드, API 키, 설정이 필요 없습니다. 공개 스토어가 패키지에
들어 있습니다. 몇 초면 끝납니다.

#### Windows (PowerShell)

인터넷에 연결된 PowerShell 5.1 또는 7에서 실행하세요. 위 한 줄 설치는 uv가 없으면
먼저 설치합니다. uv가 Python을 관리하며, faildex에는 Python 3.10 이상이 필요합니다.
ZIP 방식은 git이 필요 없습니다. git이 있다면 위 `git+https://...` 명령도 Windows에서
동작합니다. 재설치하거나 설치 방식을 바꿀 때는 `uv tool install` 뒤에 `--force`를 붙이세요.

새 PowerShell 창에서 설치를 확인하세요.

```powershell
Get-Command faildex
faildex --help
faildex demo
faildex sources
faildex ingest
```

`ingest`는 Windows 사용자 프로필 아래의 에이전트 기록을 찾아 개인 스토어를
`~/.faildex/store`에 저장합니다. 기본 기록 폴더가 없으면
`no agent logs in the default folders`를 출력하고 종료 코드 1을 반환합니다.
`--claude`, `--codex-sessions`, `--cursor`, `--antigravity`로 실제 폴더를 지정하세요.

새 창에서도 `faildex`를 못 찾으면 `uv tool update-shell`을 실행하고 PowerShell을
다시 여세요. 현재 창에만 적용하려면 `$env:Path = "$(uv tool dir --bin);$env:Path"`를
실행하세요. PowerShell 5.1의 `>`는 UTF-16으로 저장하므로 UTF-8 도구에 넘길 출력은
`| Set-Content -Encoding UTF8`로 저장하세요(PowerShell 5.1에서는 BOM 포함).
외부 명령 직후 `$LASTEXITCODE`를 확인하세요.
`| Select-Object -First N`은 출력을 중간에 끊어 종료 코드가 0이 아니게 만들 수 있습니다.

uv·Python·git이 이미 설치된 Windows 10 22H2, PowerShell 5.1, uv 0.9.10,
Python 3.13.5 환경에서 세 가지 설치 방식,
CLI 확인, 기본 경로 적재, 임시 프로필의 `link`·`link --remove`가 통과했습니다.
[명령·결과·검증 범위](docs/windows-install-verification.md)를 참고하세요.

### 저장소에서 직접

필요한 것: Python 3.10 이상과 uv. CI에서 macOS와 Linux로 시험합니다.

```bash
git clone https://github.com/dtype2100/faildex && cd faildex
make setup     # 의존성과 비밀 정보 검사 훅
make demo      # 같은 데모를 커밋된 스토어로
make eval      # 평가 표만
make test      # 테스트 160개 이상
make install   # 이 저장소를 `faildex` 명령으로 PATH에 올림
```

공개 데이터셋으로 스토어를 다시 만들기(내려받기 약 120MB):

```bash
make data          # 두 데이터셋을 고정된 리비전으로 내려받음
make build-store   # store/를 쓰고 노드 수, 크기, 메모리를 출력
```

브라우저 데모를 로컬에서 실행하기(`npm pack` 한 번에 Node 필요):

```bash
make site      # 스토어를 site/data.json으로 내보내고 Relate WebAssembly를 받음
make serve     # http://localhost:8765
```

페이지는 그래프를 Relate WebAssembly 안에서 다시 만들고 평가를 브라우저에서 다시
계산해 같은 80/117에 도달합니다. 패널마다 "Cypher 보기" 버튼으로 뒤에 있는 질의를 볼 수
있고, 콘솔에서 직접 질의할 수 있습니다. 페이지는 영어와 한국어를 지원합니다. 상단의
지구본 메뉴에서 고르거나 `?lang=ko`로 여세요.

내 기록 적재하기. 기록은 내 컴퓨터의 `~/.faildex/store`에만 남습니다.

```bash
faildex ingest    # 기본 폴더를 찾아 모두 읽음. 다른 위치는 --claude, --codex-sessions, --cursor, --antigravity DIR
faildex rules
cd ~ && faildex rules --approve 1 3   # 원하는 규칙만 ~/faildex-rules.md에 기록
faildex link      # 스킬·규칙 및 Codex/Cursor 세션·셸 훅 설치. --remove로 되돌림
```

`faildex rules --top 2` 출력 예시(공개 스토어 기준):

```text
Public demo logs (./store): 422 sessions, 627 failed calls, 25 recurring
Note: this is demo data. Index your own logs with: faildex ingest

1. `Get-ChildItem` +4 more commands — command timed out after <n> milliseconds
   52 sessions, 81 failed calls · 38 of 81 recovered within 5 calls
   Action: retry the same command; a later try worked in 21 of 38 recoveries.
   evidence (3): codex-trajectories/trajectories.train.jsonl:18, +2 more

2. `git status` — fatal: not a git repository (or any of the parent…
   24 sessions, 25 failed calls · 0 of 25 recovered within 5 calls
   Action: stop and check before retrying; no recovery on record yet.
   evidence (3): codex-trajectories/trajectories.train.jsonl:18, +2 more

Showing 2 of 25 recurring (--top 25 for all); full evidence paths: --evidence
Write a rule: faildex rules --approve 1 2 --to ~/faildex-rules.md
```

숫자는 실패 하나를 기준으로, 그 실패를 겪은 모든 명령을 합친 값입니다(`+4 more commands`).
"recovered within 5 calls"는 실패한 호출 뒤 5번 안에 같은 명령이 성공한 횟수이고,
"21 of 38 recoveries"는 그 복구 가운데 Action 줄의 방법을 쓴 횟수입니다.
`--evidence`는 근거 위치(세션 최대 3개)를 줄이지 않고 보여 줍니다.

옵션 없이 실행하면 `~/.claude/projects`, `~/.codex/sessions`, `~/.cursor/chats`,
`~/.gemini/antigravity-cli`, `~/.gemini/antigravity` 중 있는 폴더를 모두 읽습니다.

Claude Code에서 쓰기. 프로젝트의 `.claude/settings.json`(모든 세션에 쓰려면
`~/.claude/settings.json`)에 추가하세요. `faildex ingest`를 실행한 뒤에는 내 스토어를,
그 전에는 공개 스토어를 읽습니다.

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "faildex hook", "timeout": 5}
]}]}}
```

MCP 클라이언트에서 쓰기:

```json
{"mcpServers": {"faildex": {"command": "faildex", "args": ["mcp"]}}}
```

에이전트에게 이 도구를 언제 부를지 알려 주는 스킬은
[`skills/faildex/SKILL.md`](skills/faildex/SKILL.md)에 있습니다. `faildex link`가 Claude Code(`~/.claude/skills/faildex/`),
Antigravity(`faildex-rules` 플러그인 안; `--rules` 경로를 바꾸어 다시 실행하면
faildex가 만든 심볼릭 링크를 새 경로로 다시 걸고 사용자 파일은 그대로 둠),
Codex(`~/.codex/skills/faildex/`), Cursor(`~/.cursor/skills/faildex/`)에 설치하고,
`faildex link --remove`가 faildex가 만든 항목만 지웁니다.

Codex와 Cursor의 사용자 `hooks.json`에는 세션 시작 시 근거 줄을 뺀 규칙을
불러오는 훅과 셸 실행 전 알려진 실패를 경고하는 훅을 등록합니다. 기존 훅은
보존하고 변경 전에 백업하며, 제거 시 faildex 항목만 뺍니다. Codex는 `/hooks`에서
새 명령을 검토·신뢰한 뒤 새 세션을 시작해야 합니다. [훅 설정](docs/agent-hooks.md)을 참고하세요.

Cursor CLI는 훅을 지원하지만, `2026.11.19-f005e9d` 확인에서는 다른 도구의 항목이
포함된 기존 설정으로 훅이 실행되지 않았습니다. 최소 탐침 설정에서는 실행됐으며,
원인 항목은 아직 확인하지 못했습니다. 다른 도구의 훅은 보존하고 조사 중에는
설치된 스킬과 [CLI 규칙](https://cursor.com/docs/cli/using#rules)을 사용하세요.
[실험 결과와 확인 방법](docs/agent-hook-verification.md)을 남겼습니다.

## 데이터는 어디에 있나

- **`store/`**가 저장된 Relate 스토어입니다: 세션 422개, 도구 호출 14,328건,
  실패한 호출 627건, 관계 38,424개, 0.85MB. `faildex.store.open_store`가 새로 받은
  저장소에서 처음 열 때까지 포함해 엽니다.
- 공개 데이터셋 두 개로만 만들었고, 둘 다 MIT 라이선스이며
  [`build.py`](src/faildex/build.py)에 리비전이 고정돼 있습니다:
  [`crispwisp/wisp-claude-code-sessions`](https://huggingface.co/datasets/crispwisp/wisp-claude-code-sessions)
  (Claude Code),
  [`israellaguan/codex-tool-use-trajectories`](https://huggingface.co/datasets/israellaguan/codex-tool-use-trajectories)
  (Codex). 각 `Session`은 데이터셋, 리비전, 라이선스를 담은 `Source` 노드와 이어집니다.
- 이 저장소에는 개인 기록이 없습니다. 공유 스토어는 쓰는 순간 로컬 경로를 거부하고,
  커밋할 때마다 비밀 정보 검사가 돕니다.

## 평가

`make eval`은 데이터셋마다 세션을 시작 시각으로 나눠(앞 70%는 앞 기간, 뒤 30%는 뒤 기간)
뒤 기간에 일어난 실패 중 얼마나 많은 것이 이미 그래프에 있었는지 셉니다.

| | 뒤 기간 실패 | 앞 기간에 이미 있던 것 | 그중 복구 기록도 있던 것 |
|---|---|---|---|
| 모든 실패 키 | 117 | 80 (68.4%) | 48 (60.0%) |
| 실패 문구만 | 102 | 72 (70.6%) | 45 (62.5%) |

이 수치가 보여 주는 것과 보여 주지 않는 것은 [docs/evaluation.md](docs/evaluation.md)에
있습니다. 요약하면, 지식이 이미 있었다는 것을 보여 줄 뿐 경고를 받은 에이전트가 그에
따라 행동했을지는 보여 주지 않습니다. Codex 데이터셋은 Windows 프로젝트를 하는 개발자
한 명의 기록이고, 실패 하나(`command timed out`)가 80건 중 31건입니다. 이를 빼면 반복
비율은 57%입니다.

## 여러 에이전트에 걸쳐, 실제 기록에서

공개 데이터셋으로는 에이전트 사이의 경우를 보여 줄 수 없습니다. 하나는 Windows의
PowerShell, 다른 하나는 Linux의 bash라서 둘 다에 나오는 실패가 없습니다. 작성자의 기록으로는
보여 줄 수 있습니다. 아래는 2026-11-17에 `faildex ingest`로 만든 개인 스토어에서
`faildex report`로 센 건수입니다. 기록은 이 저장소에 없으므로 이 수치는 다시 계산할 수
없습니다. 같은 두 명령을 내 기록에 실행하면 내 수치를 얻을 수 있습니다.

| 에이전트 | 세션 | 도구 호출 | 실패 |
|---|---|---|---|
| Claude Code | 190 | 19,443 | 364 |
| Codex | 39 | 1,786 | 101 |
| Cursor | 59 | 2,538 | 94 |

- **실패 키 12개를 두 개 이상의 에이전트가 겪었습니다.** 한 에이전트가 겪은 실패를 다른
  에이전트도 이미 겪었습니다.
- 실패 키 57개가 두 개 이상의 세션에서 되풀이됐고, 그중 13개에 복구 기록이 있습니다.
- 훅은 가려서 말합니다. 명령 틀 197개 중 7개에만 경고가 붙습니다.

## 심사 기준

| 기준 | 볼 곳 |
|---|---|
| Relate와 연결된 맥락의 활용 | 공유 `Command`/`ErrorSig` 노드가 있는 스키마, `NEXT` 경로로 읽는 복구, 제약, 커밋된 디렉터리 스토어, 쓰는 쪽 옆의 읽기 전용 읽는 쪽, 브라우저 데모의 Relate WebAssembly에서 도는 같은 그래프와 질의, 실패마다 그려지는 이웃 |
| 기능 | 한 줄 설치와 `faildex demo`; `faildex rules`, `check`, `hook`, `mcp`, `eval`, `ingest`, `report`, `build-store`; Relate WebAssembly 브라우저 데모; macOS·Linux CI |
| 유용성 | 뒤 기간 실패의 68%가 이미 그래프에 있었음; 실제 Claude Code 세션에서 Claude가 훅의 알림을 근거로 재시도하지 않음; 되풀이된 실패에만 경고하고 나머지에는 침묵; 작성자 기록에서 세 에이전트가 공유한 실패 키 12개 |
| 문서와 재현성 | 이 파일, `docs/schema.md`, `docs/evaluation.md`(방법의 각 규칙을 지키는 테스트와 짝지음); 모든 수치는 커밋된 스토어에서 `make eval`로 나오고, 문서가 다르면 테스트가 실패하며, WebAssembly 빌드도 같은 수치에 도달 |
| 창의성 | 한 에이전트가 배운 실패가 다음 세션의 규칙과 경고가 되고, 로그 위치가 근거로 붙음 |

## AI 사용

이 프로젝트는 AI 코딩 에이전트와 함께 만들었습니다. 구현은 Claude Code(Claude), 독립
코드 검토는 Codex가 맡았습니다. 설계 결정, 데이터 선택, 결과 검토는 작성자가 했습니다.

## 라이선스

Apache-2.0. 데이터셋 라이선스는 위에 적었습니다.
