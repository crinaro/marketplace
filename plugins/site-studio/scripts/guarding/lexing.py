"""guarding.lexing -- reading a shell command line the way the guard needs: heredoc bodies are DATA (dev #875), the rest is split into
subcommands with shlex. `strip_heredocs` never raises; `split_subcommands` raises `CommandParseError` (a ValueError) on an
unbalanced quote, which the entry point turns into a deny (fail closed).
"""
import os
import re
import shlex


SEPARATORS = ("&&", "||", ";", "|", "&", "(", ")", ";;", "|&")


def _newlines_to_semicolons(cmd):
    """Replace every UNQUOTED newline with ';' so shlex sees a separator."""
    out = []
    quote = None
    esc = False
    for ch in cmd:
        if esc:
            esc = False
            out.append(ch)
            continue
        if ch == "\\" and quote != "'":
            esc = True
            out.append(ch)
            continue
        if quote:
            if ch == quote:
                quote = None
            out.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        out.append(";" if ch == "\n" else ch)
    return "".join(out)


class CommandParseError(ValueError):
    """The command names deploy.py and could not be lexed (an unbalanced quote). A ValueError, so
    the caller's fail-closed handling still applies; a class of its own so the message can say the
    command may not be a publish."""


_SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "ash", "eval", "source", ".")
_DELIM_END = set(" \t\n;&|<>()")


def _heredoc_delimiter(cmd, j):
    """(delimiter word after quote removal, index after the raw word) from `cmd[j:]`, or None when
    what follows `<<` is not a delimiter this scanner trusts (it must start with a letter,
    underscore, quote or backslash: `1 << 2` is arithmetic, not a heredoc)."""
    n = len(cmd)
    if j >= n or not (cmd[j].isalpha() or cmd[j] in "_'\"\\"):
        return None
    word = []
    while j < n and cmd[j] not in _DELIM_END:
        ch = cmd[j]
        if ch in "'\"":
            k = cmd.find(ch, j + 1)
            if k < 0:
                return None
            word.append(cmd[j + 1:k])
            j = k + 1
        elif ch == "\\" and j + 1 < n:
            word.append(cmd[j + 1])
            j += 2
        else:
            word.append(ch)
            j += 1
    return "".join(word), j


def _line_feeds_a_shell(out, cmd, i):
    """True when the physical line that holds the heredoc operator at cmd[i] runs a shell on its
    input (`bash <<EOF`, `cat <<EOF | sh`): that body is commands, not data."""
    start = "".join(out).rsplit("\n", 1)[-1]
    end = cmd.find("\n", i)
    line = start + cmd[i:(len(cmd) if end < 0 else end)]
    for seg in re.split(r"[;&|()]", line):
        for w in seg.split():
            if "=" in w and not w.startswith(("-", "=")):
                continue                    # a VAR=value prefix
            if os.path.basename(w) in _SHELLS:
                return True
            break
    return False


def strip_heredocs(cmd):
    """`cmd` with every heredoc body (and its delimiter line) removed; see HEREDOC BODIES. Quote
    aware: an operator inside quotes is text. Never raises."""
    out, pending = [], []
    i, n = 0, len(cmd)
    quote, arith = None, 0
    while i < n:
        ch = cmd[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if arith:
            arith += (ch == "(") - (ch == ")")
            out.append(ch)
            i += 1
            continue
        if cmd.startswith("$((", i) or cmd.startswith("((", i):
            k = 3 if cmd[i] == "$" else 2
            out.append(cmd[i:i + k])
            arith = 2
            i += k
            continue
        if ch == "\n":
            out.append(ch)
            i += 1
            for delim, tabs in pending:
                while i < n:
                    end = cmd.find("\n", i)
                    line = cmd[i:(n if end < 0 else end)]
                    i = n if end < 0 else end + 1
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
            pending = []
            continue
        if cmd.startswith("<<<", i):
            out.append("<<<")
            i += 3
            continue
        if cmd.startswith("<<", i):
            j = i + 2
            tabs = j < n and cmd[j] == "-"
            if tabs:
                j += 1
            while j < n and cmd[j] in " \t":
                j += 1
            parsed = _heredoc_delimiter(cmd, j)
            if parsed is None:
                out.append("<<")
                i += 2
                continue
            delim, j2 = parsed
            if not _line_feeds_a_shell(out, cmd, i):
                pending.append((delim, tabs))
            out.append(cmd[i:j2])
            i = j2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_subcommands(cmd):
    """The command as a list of token lists, heredoc bodies removed first. CommandParseError (a
    ValueError) on an unbalanced quote: the caller lets it propagate, which fails closed."""
    lex = shlex.shlex(_newlines_to_semicolons(strip_heredocs(cmd)), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    subs, cur = [], []
    try:
        for tok in lex:
            if tok in SEPARATORS or (tok and set(tok) <= set("();&|")):
                if cur:
                    subs.append(cur)
                cur = []
            else:
                cur.append(tok)
    except ValueError as exc:
        raise CommandParseError(str(exc))
    if cur:
        subs.append(cur)
    return subs
