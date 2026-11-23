import pytest

from faildex.normalize import (
    command_template,
    command_templates,
    error_signature,
    has_unquoted_glob,
    is_compound,
)

COMMANDS = [
    ("git status", "git status"),
    ("git -C repo push origin main", "git push"),
    ("cd src && pytest -q", "pytest"),
    ("FOO=1 BAR=2 npm run build", "npm run"),
    ("sudo docker compose up -d", "docker compose"),
    ("python3 -m pytest tests", "python3 -m pytest"),
    ("uv run pytest -q", "uv run pytest"),
    ("/usr/local/bin/gh api repos/x/y", "gh api"),
    ("ls -la | head -3", "ls"),
    ("echo ====", "echo"),
    ("cd /tmp; export A=1", "cd"),
    (r"C:\tools\dotnet.exe build app.sln", "dotnet build"),
    ("Get-ChildItem -Recurse src", "Get-ChildItem"),
    (r"$p='src\app\Program.cs'; Get-Content $p", "Get-Content"),
    ("$i=0; $j", None),
    ("notes.md", None),
    ("echo 'creds in ~/x; ALL repos public' >> notes", "echo"),
    ("# check the runner; look at what it does\ngit status", "git status"),
    ('geo=$(hyprctl clients -j | jq .x) && grim -g "$geo" out.png', "grim"),
    ("BASE=$(git rev-parse origin/main); git fetch -q origin", "git fetch"),
    ("timeout 180 bin/hyprbench run --task x", "hyprbench"),
    ("sudo -u customer-secret git status", "git status"),
    ("env -C /Users/alice/private git status", "git status"),
    ("ROOT=$(pwd) git status; pytest -q", "git status"),
    ("CODE=$(cat /tmp/code | tr -d '-')\nnode run.mjs", "node"),
    ("git status # TODO (slow\npytest -q", "git status"),
    ("fill() { node cdp.mjs eval x; }\ngit status", "git status"),
    ("setsid chromium --no-first-run >/dev/null 2>&1 &", "chromium"),
    ('node -e "\nconst run = async () => {\n  also();\n};\n"', "node"),
    (
        "& {\n$roots = @(\n'M:\\b2t\\arch294_loading03',\n'M:\\b2t\\arch295_press'\n);\nforeach ($r in $roots) { Import-Csv $r }\n}",
        None,
    ),
    ("npm --prefix /Users/alice/private run build", "npm run"),
    ("npm --prefix customer-secret run build", "npm run"),
    ("git customer-secret", "git"),
    ("uv run customer-secret", "uv run"),
    ("python -m customer_secret", "python -m"),
    ("make customer-secret", "make"),
    ("git /Users/alice/private", "git"),
    ("uv run ./scripts/secret-name.py", "uv run"),
    ("python -m /Users/alice/x", "python -m"),
    ("if [ -f a ]; then\n  git status\nfi", "git status"),
    ("cat <<'EOF' > notes\nplain words here\nEOF\ngit add notes", None),
    ("gh 2>/dev/null", "gh"),
    ("$roots = @(\n'arch294_loading03',\n'arch295_press'\n)\nGet-Item $roots", "Get-Item"),
    ("$rows = @{\n  diamond = 'a'\n}\n$rows.diamond", "<script>"),
    ("$text = @'\nimport math\nprint(1)\n'@\n$text | python -", "<script>"),
]

SIGNATURES = [
    ('error: "customer-secret-' + "x" * 210 + '"', "error: <s>"),
    ('error: cannot open "customer-secret-never-closed', "error: cannot open <s>"),
    (
        "the user doesn't want this; it can't proceed: error",
        "the user doesn't want this; it can't proceed: error",
    ),
    ("Traceback (most recent call last):\nKeyError: 1\nMY_PRIVATE_DATA", "keyerror: <n>"),
    ("Traceback (most recent call last):\n  File x\nplain words", None),
    (
        'Traceback (most recent call last):\n  File "/src/error.py", line 1\nException: boom\nordinary',
        "exception: boom",
    ),
    ('Traceback (most recent call last):\n  File "/src/error.py", line 1\nordinary output', None),
    (
        r"rg: src\app\Frame*.cs: The system cannot find the file",
        "rg: <path>: the system cannot find the file",
    ),
    (
        "src/a.c:10:5: error: unknown type name 'foo'",
        "<path>:<n>:<n>: error: unknown type name <s>",
    ),
    ("src/app.cs:12: throw new InvalidOperationException(x);", None),
    ('12: Console.Error.WriteLine("usage error: needs [start]', None),
    ("(eval):1: no matches found: README*", "no matches found: <glob>"),
    ("(eval):3: no matches found: --include=*.py", "no matches found: <glob>"),
    ("zsh:1: no matches found: .aider*", "no matches found: <glob>"),
    ("zsh:12: no matches found: src/*.yaml", "no matches found: <glob>"),
    ("Exit code 1\n(eval):1: ==== not found", "=<word> not found"),
    ("(eval):3: ===== not found", "=<word> not found"),
    ("zsh:1: = not found", "=<word> not found"),
    ("(eval):2: =tests not found", "=<word> not found"),
    ("(eval):1: command not found: foo", "(eval):<n>: command not found: foo"),
    (
        "Traceback (most recent call last):\n  File \"/a/b.py\", line 3\nKeyError: 'name'",
        "keyerror: <s>",
    ),
    (
        "fatal: not a git repository (or any of the parent directories): .git",
        "fatal: not a git repository (or any of the parent directories): .git",
    ),
    (
        (
            "Exit code: 1\nWall time: 0.6 seconds\nOutput:\n\nAt line:1 char:5\n"
            "The term 'foo' is not recognized as the name of a cmdlet"
        ),
        "the term <s> is not recognized as the name of a cmdlet",
    ),
    ("cat: /Users/me/x/y.txt: No such file or directory", "cat: <path>: no such file or directory"),
    (
        r"Cannot find path 'C:\Users\me\x' because it does not exist.",
        "cannot find path <s> because it does not exist.",
    ),
    ("command timed out after 120000 milliseconds", "command timed out after <n> milliseconds"),
    ("ModuleNotFoundError: No module named 'relate'", "modulenotfounderror: no module named <s>"),
    (
        "ERROR: file or directory not found: tests/test_billing.py",
        "error: file or directory not found: <path>",
    ),
    (
        "fatal: Could not resolve host: git.acme-internal.example",
        "fatal: could not resolve host: <host>",
    ),
    (
        "fatal: unable to access 'https://github.com/a/b.git/': timeout",
        "fatal: unable to access <s>: timeout",
    ),
]


@pytest.mark.parametrize(("command", "expected"), COMMANDS)
def test_command_template(command, expected):
    assert command_template(command) == expected


@pytest.mark.parametrize(("text", "expected"), SIGNATURES)
def test_error_signature(text, expected):
    assert error_signature(text) == expected


def test_same_failure_in_two_sessions_gets_one_signature():
    first = error_signature("cat: /Users/alice/repo/a.txt: No such file or directory")
    second = error_signature("cat: /home/bob/other/b.txt: No such file or directory")
    assert first == second


def test_empty_output_has_no_signature():
    assert error_signature("Exit code 1\n\n") is None
    assert command_template("   ") is None


def test_plain_output_is_not_a_signature():
    assert error_signature("sites/findings.md:12: - it is a mere backend selector") is None


def test_compound_means_several_different_programs():
    from faildex.normalize import is_compound

    assert is_compound("git status && python -c 'raise ValueError()'")
    assert not is_compound("cd repo && git status")
    assert not is_compound("git status | head -3")
    assert is_compound("python pass.py; python fail.py")
    assert is_compound("git push || echo ignored")
    assert is_compound("ROOT=$(pwd) git status; pytest -q")
    assert is_compound("git status && (pytest -q; ruff check .)")
    assert is_compound("git status # TODO (slow\npytest -q")
    assert not is_compound("geo=$(hyprctl clients -j | jq .x)\ngrim out.png")
    assert is_compound("git push; echo done")
    assert not is_compound("echo hello")


def _assert_heredoc_skipped(command: str) -> None:
    assert command_template(command) is None
    assert command_templates(command) == []
    assert not is_compound(command)


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF'\n$(private_customer_command)\nEOF",
        "cat <<\\EOF\n$(private_customer_command)\nEOF",
        "cat <<'END DATA'\n$(private_customer_command)\nEND DATA",
        "cat <<EOF\n$(private_customer_command)\nEOF\ngit status",
        "cat <<'END-DATA'\n$(private_customer_command)\nEND-DATA",
        "cat <<A <<B\nfirst\nA\n$(private_customer_command)\nB",
        "cat <<EOF\n$(private_customer_command)",
        "cat <<EOF | grep x",
    ],
)
def test_heredoc_scripts_extract_no_commands(command):
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize("delimiter", ["EOF", "'EOF'", '"EOF"'])
@pytest.mark.parametrize(
    "operator, indent",
    [("<<", " "), ("<<", "\t"), ("<<", " \t"), ("<<-", " "), ("<<-", "\t ")],
)
def test_heredoc_terminator_indentation_keeps_private_body_hidden(delimiter, operator, indent):
    command = f"cat {operator}{delimiter}\nbody\n{indent}EOF\n$(private_customer_command)\nEOF\ngit status"
    _assert_heredoc_skipped(command)


def test_plain_heredoc_indented_first_line_is_not_the_terminator():
    _assert_heredoc_skipped("cat <<EOF\n EOF\n$(private_customer_command)\nEOF")


@pytest.mark.parametrize("delimiter", ["EOF", "'EOF'", '"EOF"'])
def test_dash_heredoc_accepts_tab_indented_final_terminator(delimiter):
    _assert_heredoc_skipped(f"cat <<-{delimiter}\n$(private_customer_command)\n\t\tEOF\ngit status")


@pytest.mark.parametrize(
    "opener, misleading, delimiter",
    [
        (r"\EOF", r"\EOF", "EOF"),
        ("E'OF'", "E", "EOF"),
        ('E"OF"', "E", "EOF"),
        ('"E O F"', "E", "E O F"),
        ("'E O F'", "E", "E O F"),
        (r'"E\$OF"', r"E\$OF", "E$OF"),
        (r'"E\`OF"', r"E\`OF", "E`OF"),
    ],
)
def test_shell_quote_removal_prevents_premature_heredoc_end(opener, misleading, delimiter):
    command = f"cat <<{opener}\n{misleading}\n$(private_customer_command)\n{delimiter}\ngit status"
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize(
    "suffix",
    [
        "| grep x",
        "&& next",
        "; ls README*",
        "| grep x && git status",
    ],
)
def test_heredoc_opening_line_commands_are_also_skipped(suffix):
    _assert_heredoc_skipped(f"cat <<EOF {suffix}\n$(private_customer_command)\nEOF")


@pytest.mark.parametrize(
    "command",
    [
        "git status <<'EOF'\nhello\nEOF\necho 'still << here'",
        "cat <<EOF # <<\n$(private_customer_command)\nEOF\ngit status",
        "echo 'still << here'",
        'echo "still << here"',
        "git status # <<",
        "cat <<< 'hello'\ngit status",
        "cat <<-EOF\n\t$(private_customer_command)\n\tEOF\ngit status",
        "echo \"$(grep '<<' file.txt)\"",
        'echo "$((1 << 2)) $(ls README*)"',
        "cat <<EOF | grep x",
    ],
)
def test_any_double_lt_skips_the_entire_script(command):
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize(
    "command",
    [
        # Round 5 P1: heredoc inside double-quoted $(...) with body `)`
        "echo \"$(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n)\"",
        # Unquoted $(...) containing a heredoc and body `)`
        "x=$(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n)",
        "x=$(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n) && git status",
        # Real outer command with heredoc inside double-quoted $(...)
        "git commit -m \"$(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n)\" && git push",
        # Quotes and `)` inside heredoc body inside double-quoted $(...)
        'echo "$(cat <<\'EOF\'\n"\n$(private_customer_command)\nEOF\n)"',
        'echo "$(cat <<\'EOF\'\n)"\n$(private_customer_command)\nEOF\n)"',
        "echo \"$(cat <<'EOF'\n'\n$(private_customer_command)\nEOF\n)\"",
        "echo \"$(cat <<-'EOF'\n\t)\n\t$(private_customer_command)\n\tEOF\n)\"",
        "echo \"$(cat <<E'OF'\nE\n)\n$(private_customer_command)\nEOF\n)\"",
        # Entire substitution yields nothing when a heredoc appears anywhere inside it
        "echo \"$(echo hi && cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n)\"",
        "f=$(git status && cat <<'EOF'\n$(private_customer_command)\nEOF\n)",
        "echo \"$(ls $(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n))\"",
        # Backtick substitutions with heredocs
        "echo \"`cat <<'EOF'\n$(private_customer_command)\nEOF\n`\"",
        'echo "`cat <<\'EOF\'\n"\n$(private_customer_command)\nEOF\n`"',
        "echo \"`cat <<'EOF'\n`\n$(private_customer_command)\nEOF\n`\"",
        "echo `cat <<'EOF'\n\\`\n$(private_customer_command)\nEOF\n`",
        "f=`cat <<'EOF'\n$(private_customer_command)\nEOF\n`",
        'echo "$(case $x in a) cat <<\'EOF\'\n"\n$(private_customer_command)\nEOF\n;; esac)"',
    ],
)
def test_round5_heredoc_substitutions_never_leak(command):
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status && cat <<EOF\n$(private_customer_command)",
        "echo \"$(cat <<'EOF'\n$(private_customer_command)\n)\"",
        'echo "$(cat <<EOF\n\t$(private_customer_command)\n\tEOF\n)"',
        "echo \"`cat <<'EOF'\n$(private_customer_command)\n`\"",
        "echo `cat <<'EOF'\n$(private_customer_command)\n`",
    ],
)
def test_unclosed_heredoc_anywhere_skips_the_entire_script(command):
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize(
    "command, forbidden",
    [
        # Round 6 P1-1: backtick comments and escaped/nested quotes around heredocs
        (
            "echo `echo hi # `\ncat <<'EOF'\n`\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            'echo "`echo \\"\'\\"`"\ncat <<\'EOF\'\n$(private_customer_command)\nEOF',
            "private_customer_command",
        ),
        (
            'echo "`echo \\"`\ncat <<\'EOF\'\n$(private_customer_command)\nEOF\n`"',
            "private_customer_command",
        ),
        (
            "echo `echo \\\"`\ncat <<'EOF'\n\" `\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            'echo "`echo \\"\\"`" && cat <<\'EOF\'\n$(private_customer_command)\nEOF',
            "private_customer_command",
        ),
        (
            "echo `echo '\\''`\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "echo `echo '`'`\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        # Round 6 P1-2: unpaired backtick inside double quotes
        (
            'echo "`" && cat <<\'EOF\'\n$(private_customer_command)\nEOF\n"',
            "private_customer_command",
        ),
        (
            "echo \"`\"; cat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        # Round 6 P1-3: case after pipeline/compound prefix, in subshell, and extglob patterns
        (
            "! case $x in a) ;; esac\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "if case $x in a) true ;; esac; then cat <<'EOF'\n$(private_customer_command)\nEOF\nfi",
            "private_customer_command",
        ),
        (
            "(case $x in a) echo hi ;; esac)\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            (
                'echo "$( (case $x in a) echo hi ;; esac)\n'
                "cat <<'EOF'\n$(private_customer_command)\nEOF\n)\""
            ),
            "private_customer_command",
        ),
        (
            "case $x in @(a|b)) echo hi ;; esac\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            (
                "echo \"$(case $x in @(a|b)) cat <<'EOF'\n"
                ')\n$(private_customer_command)\nEOF\n;; esac)"'
            ),
            "private_customer_command",
        ),
        # Round 6 P1-4: ANSI-C $'...' quoting
        (
            "echo $'don\\'t'\ncat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "echo $'\\'' && cat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        # Round 6 P1-5: ${VAR:-"..."} nested quotes inside parameter expansion
        (
            'echo "${X:-"}"}" && cat <<\'EOF\'\n$(private_customer_command)\nEOF',
            "private_customer_command",
        ),
        (
            "echo \"${X:-don't}\" && cat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        # Round 6 P1-6: $(( and (( with heredocs vs bitshift
        (
            "echo $(( $(cat <<'EOF'\n)\n$(private_customer_command)\nEOF\n) ))",
            "private_customer_command",
        ),
        (
            "echo $((\ncat <<'EOF'\n))\n$(private_customer_command)\nEOF\n)); echo ok",
            "private_customer_command",
        ),
        (
            "echo $((cat <<'EOF'\n))\n$(private_customer_command)\nEOF\n); echo ok )",
            "private_customer_command",
        ),
        (
            "((cat <<'EOF'))\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "(( x = 1 << 2 ))\ncat <<'EOF'\n2\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        # Round 6 P1-7: empty heredoc delimiter <<'' without closing empty line
        ("cat <<''\n$(private_customer_command)", "private_customer_command"),
        ("git status && cat <<''\n$(private_customer_command)", "private_customer_command"),
        ("git status && cat <<''\n$(private_customer_command)\n", "private_customer_command"),
        # PowerShell lookalike header + heredoc
        (
            "[ -f a ] && echo \"`t\" && cat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "[ -f a ] && echo \"`date`\" && cat <<'EOF'\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "echo @'\n' && cat <<'EOF'\n'@\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
        (
            "$x = @'\n' && cat <<'EOF'\n'@\n$(private_customer_command)\nEOF",
            "private_customer_command",
        ),
    ],
)
def test_round6_p1_inputs_never_leak_private_commands(command, forbidden):
    assert forbidden not in command_templates(command)
    _assert_heredoc_skipped(command)


@pytest.mark.parametrize(
    "command",
    [
        # Round 7 P1 (A): ANSI-C $'...' heredoc delimiter
        ": <<$'E\\nE'\nprivate_customer_command\nE",
        ": <<$'E\nE'\nprivate_customer_command\nE",
        # Round 7 P1 (B): line continuation inside unquoted heredoc body
        ": <<E\nx\\\nE\nprivate_customer_command\nE",
    ],
)
def test_round7_p1_heredoc_inputs_return_empty(command):
    _assert_heredoc_skipped(command)


def test_unclosed_empty_delimiter_heredoc_skips_entire_script():
    _assert_heredoc_skipped("git status && cat <<''\n$(private_customer_command)")
    _assert_heredoc_skipped("git status && cat <<''\n$(private_customer_command)\n")
    _assert_heredoc_skipped("cat <<''\nhello\n\ngit status")


def test_heredoc_does_not_mark_compound():
    for cmd in [
        "echo \"$(cat <<'EOF'\n*.py\nfoo || bar\n)\n$(private_customer_command)\nEOF\n)\"",
        "cat <<EOF | ls *.py\nfoo\nEOF",
        "echo '<<' && ls *.py | grep x",
        "cat <<EOF || true\nfoo\nEOF",
        "cat <<EOF | grep x",
    ]:
        _assert_heredoc_skipped(cmd)


def test_error_signature_keeps_double_lt_in_failure_output():
    assert error_signature("error: conflict marker << found") == "error: conflict marker << found"


def test_zsh_glob_failures_share_one_signature():
    """Literal globs must not split the same zsh NOMATCH error across keys."""
    eval_sig = error_signature("(eval):1: no matches found: README*")
    zsh_sig = error_signature("zsh:1: no matches found: --include=*.py")
    assert eval_sig == zsh_sig == "no matches found: <glob>"


@pytest.mark.parametrize("prefix", ["zsh:", "zsh:12:", "(eval):", "(eval):3:"])
def test_nomatch_without_line_number_masks_the_entire_glob(prefix):
    assert (
        error_signature(f"{prefix} no matches found: private-customer-*")
        == "no matches found: <glob>"
    )


@pytest.mark.parametrize(
    "command",
    [
        "ls README* readme*",
        "for f in *.x; do ls README*; done",
        "for d in a b; do ( ls README* ); done",
        "( ls README* readme* )",
        "f=$(ls README* readme* | head -1)",
        'echo "$(ls README*)"',
        "echo `ls README*`",
        'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done',
        "ls a[0]",
        'echo "a \\\\"*.private',
        "ls \\\n*.py",
        "ls ${x:-$(ls *.private)}",
        "[[ $(ls *.private) == x ]]",
        "[[ `ls *.private` == x ]]",
        "echo $(( $(ls *.private) + 1 ))",
        "(( x = $(ls *.private) ))",
        "[[ $(( $(ls *.private) + 1 )) == 0 ]]",
        r"Get-ChildItem C:\foo\*.cs",
    ],
)
def test_has_unquoted_glob_detects_active_unquoted_globs(command):
    assert has_unquoted_glob(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "ls '*.py'",
        'ls "*.py"',
        r"ls \*.py",
        r"ls \?.txt",
        "echo '$(ls README*)'",
        'echo "a \\"*.private"',
        "[ -f a ] && git status",
        "[[ -f a ]] && git status",
        "[[ $x == *.py ]] && git status",
        "echo $(( 2 * 3 ))",
        "(( x = 2 * 3 ))",
        "echo ${arr[0]} ${arr[*]}",
        "git status # ls *.py",
        "f() { ls *.py; }",
        '"f" () { ls *.py; }',
        "f ( ) { ls *.py; }",
        "for x in a; do f() { ls *.py; }; done",
        "for x in a; do public.helper()\n{\nls *.private\n}; done",
        "ls prefix'*.private'",
        r'echo "C:\foo" \*.private',
        "cat <<'EOF'\n$(ls *.py)\nEOF",
        "echo @'\n*.private\n'@",
    ],
)
def test_has_unquoted_glob_avoids_false_positives(command):
    assert not has_unquoted_glob(command)


@pytest.mark.parametrize(
    "command",
    [
        # Issue #32 case 1: function definitions with prefixes, quoted names, spaced parens, multiline bodies
        "time private_customer_function() { value=$(private_customer_command); }",
        '"private_customer_function" () { value=$(private_customer_command); }',
        "private_customer_function ( ) { value=$(private_customer_command); }",
        "time private_customer_function ( ) { value=$(private_customer_command); }",
        "private_customer_function()\n{\nprivate_customer_command\n}",
        "function private_customer_function\n{\nprivate_customer_command\n}",
        '"public.helper" ()\n{\nprivate_customer_secret\n}',
        '"public".helper()\n{\nprivate_customer_secret\n}',
        "public.helper \\\n()\n{\nprivate_customer_secret\n}",
        "time -p private_customer_function()\n{\nprivate_customer_secret\n}",
        "private_customer_function() \\\n{\nprivate_customer_secret\n}",
        "(( private_customer_secret * other ))",
        # Issue #32 case 3: line-continuation split ANSI-C $'...' strings
        "echo $\\\n'don\\'t; private_customer_secret; \\'x'",
        "echo $\\\r\n'don\\'t; private_customer_secret; \\'x'",
        "echo $\\\n\\\n'don\\'t; private_customer_secret; \\'x'",
        # Issue #32 case 4: multiline (( ... )) and $(( ... ))
        "((\nprivate_customer_secret * other\n))",
        "echo $((\nprivate_customer_secret * other\n))",
        'echo "$((\nprivate_customer_secret * other\n))"',
        "((\n(a + b)\nprivate_customer_secret\n))",
    ],
)
def test_issue32_blocked_or_function_inputs_never_leak(command):
    assert command_template(command) is None
    assert command_templates(command) == []
    assert not is_compound(command)
    assert not has_unquoted_glob(command)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # Issue #32 case 2: PowerShell here-strings as command arguments
        ("echo @'\nIt's private; private_customer_secret\n'@", "echo"),
        ('Write-Output @"\n"; private_customer_secret\n"@', "Write-Output"),
        # Single-line ANSI-C $'...' and escaped \$'...' never leak later words
        ("echo $'don\\'t; private_customer_secret; \\'x'", "echo"),
        (r'''echo \$'a\'"b' ; private_customer_secret; 'c"''', "echo"),
        (r'''echo "C:\foo" \$'a\'"b' ; private_customer_secret; 'c"''', "echo"),
        # Normal line continuations are not blocked by the ANSI-C continuation guard
        ("git status \\\n--short", "git status"),
        ("ls \\\n*.py", "ls"),
        # Quoted multiline (( is data, not arithmetic
        ('echo "((\nprivate_customer_secret\n))"', "echo"),
    ],
)
def test_issue32_argument_strings_and_normal_continuations_preserve_only_program(command, expected):
    assert command_template(command) == expected
    assert command_templates(command) == [expected]
    assert not is_compound(command)


def test_quoted_or_operator_is_not_compound():
    assert not is_compound("git status 'a || b'")
    assert not is_compound('git status "a || b"')
    assert not is_compound('git status "a \\"|| b"')
    assert not is_compound("git status # a || b")
    assert is_compound("cd a || git status")
    assert is_compound('git status "$(ls a || ls b)"')


ADVERSARIAL_LONG_INPUTS = [
    "a" * 12000,
    "a.b-" * 3000,
    "time -p " + "a" * 12000,
    "a \\\n" * 3000,
    "env \\\n" * 2000 + "ls",
    "A=1 " * 3000 + "ls",
    r"\a" * 5000 + " *.x",
    "foo() " + "\\\n" * 5000 + "{\necho x\n}",
    "( (" * 1800 + "ls *.x" + ") )" * 1800,
    "a'b" * 4000,
    "a'" + "x" * 12000,
    r'echo "a \"b" ' * 1000,
    r"echo \$'a' " * 1200,
    "echo $'\\'' " * 1500,
    "$(" * 5500,
    "$((" * 3500,
    "((\n" * 3500,
    "${" * 5500,
    "((" * 5500,
    "[" * 12000,
    "`" * 12000,
    "( " * 5500,
    "# comment\n" * 1500,
    (" " * 10 + "\n") * 1500,
    "@'\n" * 4000,
]


@pytest.mark.parametrize("text", ADVERSARIAL_LONG_INPUTS)
def test_normalize_linear_time_on_adversarial_10k_inputs(text):
    import time

    assert len(text) >= 10000
    for fn in (
        command_template,
        command_templates,
        is_compound,
        has_unquoted_glob,
        error_signature,
    ):
        started = time.monotonic()
        fn(text)
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, f"{fn.__name__} took {elapsed:.3f}s on len={len(text)}"


@pytest.mark.parametrize(
    "command",
    [
        "echo =====",
        "cat x; echo ====",
        '[ "$a" == b ] && echo y',
        "echo $(echo ====)",
        "(echo ==tests)",
    ],
)
def test_unquoted_double_equals_words_are_found(command):
    from faildex.normalize import has_unquoted_equals

    assert has_unquoted_equals(command)


@pytest.mark.parametrize(
    "command",
    [
        "echo '====='",
        'echo "====="',
        r"echo \=====",
        "FOO==1 make",
        "git log --format==%h",
        "[[ $a == b ]]",
        "echo a==b",
        "# =====",
        "echo =foo",
        "printf '%s' prefix\\ ====",
        "printf '%s' prefix\\ ==== 'C:\\temp\\x'",
        "cat <<EOF\n=====\nEOF",
        "ls",
    ],
)
def test_quoted_or_mid_word_equals_are_not(command):
    from faildex.normalize import has_unquoted_equals

    assert not has_unquoted_equals(command)


@pytest.mark.parametrize(
    "text",
    [
        # Token-shaped strings are assembled so the source holds none for secret scanners.
        "error: api_key=" + "sk_" + "live_FAKEDEMO1234567890",
        "fatal: token: ghp_ABCDEFGHIJKLMNOPQRSTuvwxyz0123",
        "Error: invalid password=hunter2hunter2",
        "error: " + "AKIA" + "ABCDEFGHIJKLMNOP rejected",
        "error: bad header Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc",
        "error: slack xoxb-1234567890-abcdefghij failed",
    ],
)
def test_secrets_never_reach_a_signature(text):
    sig = error_signature(text)
    assert sig and "<secret>" in sig
    for leaked in ("fakedemo", "ghp_abc", "hunter2", "akiaabc", "eyjhbg", "xoxb-123"):
        assert leaked not in sig


@pytest.mark.parametrize(
    ("command", "templates", "compound"),
    [
        ("git log | head -5", ["git log", "head"], False),
        ("rg foo src | sort | uniq -c", ["rg", "sort", "uniq"], False),
        ("ls 2>&1 | tee out.log", ["ls", "tee"], False),
        ("make |& grep error", ["make", "grep"], False),
        ("Get-ChildItem | Select-Object Name", ["Get-ChildItem", "Select-Object"], False),
        ("Get-ChildItem | select-object Name", ["Get-ChildItem", "select-object"], False),
        ("ls | git status", ["ls", "git status"], True),
        ("ls | xargs rm", ["ls", "xargs"], True),
        ("cat x.json | python3 -m json.tool", ["cat", "python3 -m json.tool"], True),
        ("ls 'a | b'", ["ls"], False),
        ("echo x >| out.txt", ["echo"], False),
        ("n=$(ls | wc -l)", [], False),
        ("a || b", ["a", "b"], True),
        ("git push | true", ["git push"], True),
        ("git push | echo done", ["git push"], True),
        ("git log $'don\\'t | git push origin main'", ["git log"], False),
        ("ls [ | git push origin main", ["ls", "git push"], True),
        ("git log | (git push origin main)", ["git log", "git push"], True),
        ("git log | { head -5; }", ["git log", "head"], False),
    ],
)
def test_pipes_are_looked_up_part_by_part_and_compound_only_past_a_filter(
    command, templates, compound
):
    assert command_templates(command) == templates
    assert is_compound(command) is compound
    if templates and "|" in command and "||" not in command:
        assert command_template(command) == templates[0]  # the first command is unchanged


@pytest.mark.parametrize(
    ("command", "template"),
    [
        ("time -p python3 x.py", "python3"),
        ("sudo -n make", "make"),
        ("sudo -E -H make", "make"),
        ("sudo -u root make", "make"),
        ("nice -n 5 make", "make"),
        ("timeout -s KILL 10 pytest", "pytest"),
        ("env -i make", "make"),
        ("command -p make", "make"),
        ("stdbuf -o L make", "make"),
        ("time -o out.txt make", "make"),
    ],
)
def test_wrapper_options_without_a_value_are_not_the_program(command, template):
    assert command_template(command) == template
