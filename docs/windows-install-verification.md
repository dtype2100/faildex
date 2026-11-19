# Windows installation verification

Verified 2026-11-19 on faildex commit
`7ea7cb1600fe3a8bd9414adb1e5ac6c5c7f6737a` (version 0.1.0).
The initial one-line installation and fresh SSH-session PATH check were performed
by the previous PO; the remaining checks below were completed by the receiving PO.

## Environment

| Component | Version |
|---|---|
| Windows | Windows 10 22H2, 10.0.19045 |
| PowerShell | 5.1.19041.6456 |
| uv | 0.9.10, already installed |
| Python | 3.13.5, already installed |
| Git | 2.42.0.windows.2, already installed |

Commands ran in PowerShell through an existing SSH terminal, not a Windows
developer shell. faildex was absent before the initial installation.

## Installation methods

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/dtype2100/faildex/main/install.ps1 | iex"
uv tool install --force https://github.com/dtype2100/faildex/archive/refs/heads/main.zip
uv tool install --force git+https://github.com/dtype2100/faildex
```

| Check | Result / output |
|---|---|
| One-line installer | Exit 0; `Installed 1 executable: faildex`; `faildex is installed.` |
| Fresh SSH/PowerShell session after installer | `Get-Command faildex` found `C:\Users\jw160\.local\bin\faildex.exe` |
| ZIP reinstall | `ZIP_INSTALL_EXIT=0`; `Installed 1 executable: faildex` |
| Git reinstall | `GIT_INSTALL_EXIT=0`; resolved to commit `7ea7cb1600fe3a8bd9414adb1e5ac6c5c7f6737a` |
| New PowerShell process after each reinstall | `powershell -NoLogo -NoProfile -Command '...'`; same executable path, help exit 0, `faildex 0.1.0` |

`--force` was used for the two manual methods because faildex was already
installed by the first method. These were sequential reinstalls, not three
independent clean machines. New child PowerShell processes inherit their parent's
PATH; the initial check also used a fresh SSH connection. The executable folder
was already on PATH before installation.

## CLI checks

| Command | Result / output |
|---|---|
| `faildex --help` | Exit 0 |
| `faildex --version` | `faildex 0.1.0` |
| `faildex sources` | Exit 0; two pinned datasets listed below |
| `faildex demo` | Exit 0; 50 lines; final Windows output equals current macOS output by SHA-256 |
| `faildex ingest` | Exit 0; found all five default folders; `ingested 1,343 calls into C:\Users\jw160\.faildex\store`; `sessions 24  calls 1,343  failed 68  failure keys 24` |
| `faildex ingest` in an empty temporary profile | Exit 1; `error: no agent logs in the default folders`; lists defaults and explicit folder options |

The public sources were:

```text
wisp crispwisp/wisp-claude-code-sessions c2c90b59174318ab0b163ec9c9ac82bb879288ce
codex-trajectories israellaguan/codex-tool-use-trajectories 69019b2c717fe7be8f4fab16b317e4b8bbcf831b
```

Final demo comparison: capture stdout as lines, join with LF without a trailing
LF, encode as UTF-8, then hash with SHA-256 on both systems:

```text
ff4a21cfcc221b052eb6138660707380e463d5d6277c94fe11178ae43bd42704
```

## Isolated agent integration

Created a unique `faildex-windows-<guid>` directory under `$env:TEMP`, saved and
temporarily replaced both `USERPROFILE` and `HOME`, then created `.claude`,
`.codex`, `.cursor` and `.gemini/antigravity-cli` there. All `link` commands below
used that temporary profile and the default rules path.

| Command / inspection | Result |
|---|---|
| `faildex link --dry-run` | Exit 0; planned changes printed; rules file remained absent |
| `faildex link` | Exit 0; Claude import and four agent skills installed; Antigravity rules symlink created |
| Inspect generated files | Claude import pointed inside the temporary profile; Antigravity rules contained the generated header |
| `faildex link --remove` | Exit 0; no `SKILL.md` files or Antigravity plugin remained; Claude import removed |
| Restore environment | `USERPROFILE` restored to `C:\Users\jw160`; original `HOME` restored |

Actual global agent configuration was not changed. Cleanup confirmed
`TEMP_PROFILE_LEFT=False` and `DEMO_FILE_LEFT=False`: the temporary profile and
previous PO's `fx-demo.txt` were removed. faildex and the private ingest store are
intentionally retained on the PC.

## Limits and interpretation

- No faildex defect was observed; no issue or fix branch was needed.
- uv/Python bootstrapping on a machine without them was not exercised.
- PowerShell 7, Windows 11, and a user without symlink privileges were not tested
  on this PC. Antigravity's copy fallback was not exercised here.
- A missing log folder is an expected exit 1, not an installation failure.
- PowerShell 5.1 output redirection defaults to UTF-16. Truncating native output
  with `Select-Object -First N` can cause a nonzero native exit code; the help
  check used complete output redirected to `$null` instead.
- Three installation paths were checked once each; no further installation
  verification rounds were run.
