#!/usr/bin/env python3
"""開発者が自分で書く計算コア(engine/cpp・engine/cuda)を、サブエージェントが書き換えないようにする PreToolUse フック。

CLAUDE.md の役割分担で、この2つのフォルダは開発者が学習のために自分で書く場所になっている。
test-runner・cpp-tutor・code-reviewer の各サブエージェントに付けている(.claude/agents/*.md の hooks)。

- Edit / Write / NotebookEdit:書き込む先(file_path / notebook_path)が守る場所の中なら止める
- Bash:守る場所を書き換えそうなコマンドを止める
  - リダイレクト(> や >>)、tee、sed -i などの「その場で書き換える」コマンド
  - cp・mv・rm・touch・mkdir など、ファイルを作る・消す・動かすコマンド(守る場所の親フォルダごと消す・動かすのも含む)
  - 作業中の変更を消してしまう git コマンド(reset --hard、checkout -- .、restore、clean、stash など)。
    これはフォルダに関係なく止める(開発者のまだコミットしていない C++ のコードが消えるのを防ぐため)

コマンドの文字列から推測しているので、完全ではない(Python などのプログラムが中でファイルを書くのは見抜けないことがある)。
サブエージェントの指示にも「書き換えない」と書いてあり、このフックは念のための安全網。
テスト:tests/python/test_protect_hook.py

終了コード 2 で終わると、ツール呼び出しは止まり、stderr の文が Claude に返される。
"""

from __future__ import annotations

import json
import os
import shlex
import sys

PROTECTED_DIRS = ("engine/cpp", "engine/cuda")

# コマンドの区切り(shlex の punctuation_chars でひとかたまりになる記号)
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;", ";&"}
# 出力先を書き換えるリダイレクト
WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
# コマンドの前に付いて、本体のコマンドを実行するだけのもの
PREFIX_COMMANDS = {"sudo", "env", "command", "nice", "nohup", "time", "builtin", "exec", "stdbuf"}
# 引数のファイルの中身を書き換える・作るコマンド(引数が守る場所の中なら止める)
WRITING_COMMANDS = {
    "tee",
    "touch",
    "truncate",
    "mkdir",
    "vi",
    "vim",
    "nvim",
    "nano",
    "emacs",
    "ed",
    "ex",
}
# 消す・動かすコマンド(守る場所の中か、守る場所を含む親フォルダなら止める)
REMOVING_COMMANDS = {"rm", "rmdir", "unlink", "shred", "mv"}
# 権限を変えるコマンド(-R のときは親フォルダも止める)
MODE_COMMANDS = {"chmod", "chown", "chgrp"}
# 最後の引数(コピー先)が守る場所なら止めるコマンド
COPY_COMMANDS = {"cp", "install", "rsync", "ln", "scp"}
# -i / --in-place のときだけ、引数のファイルをその場で書き換えるコマンド
IN_PLACE_COMMANDS = {"sed", "perl", "clang-format"}
# 作業ツリーの変更を消す・上書きする git のサブコマンド
DESTRUCTIVE_GIT = {"restore", "clean", "stash", "apply", "am", "rm", "mv"}
GLOB_CHARS = set("*?[")


def protected_roots(project_dir: str) -> list[str]:
    return [os.path.realpath(os.path.join(project_dir, rel)) for rel in PROTECTED_DIRS]


def _resolve(path: str, cwd: str) -> str:
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))


def _inside(target: str, root: str) -> bool:
    return target == root or target.startswith(root + os.sep)


def touches(path: str, cwd: str, roots: list[str], *, include_ancestors: bool = False) -> bool:
    """path が守る場所の中か(include_ancestors なら、守る場所を含む親フォルダも当てはまる)。

    ワイルドカード(* ? [)を含むときは、それが置かれたフォルダで判定する。
    """
    if not path or path.startswith("-"):
        return False
    if GLOB_CHARS & set(path):
        # 例:engine/cpp/*.o → engine/cpp で判定する。rm -r ./* のように親フォルダで広く当たるものは
        # include_ancestors(再帰的に消す・動かすとき)のときだけ止める
        head = path
        while head and GLOB_CHARS & set(head):
            head = os.path.dirname(head)
        path = head or "."
    target = _resolve(path, cwd)
    for root in roots:
        if _inside(target, root):
            return True
        if include_ancestors and root.startswith(target.rstrip(os.sep) + os.sep):
            return True
    return False


def split_commands(command: str) -> list[list[str]]:
    """コマンドの文字列を、区切り(; && || | など)で分けた単純なコマンドの並びにする。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        # 引用符が閉じていないなど。分けられないときは、空白で区切っただけで調べる
        tokens = command.split()
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def strip_prefixes(words: list[str]) -> list[str]:
    """先頭の「変数=値」や sudo・env などを外して、本体のコマンドから始まる並びにする。"""
    i = 0
    while i < len(words):
        word = words[i]
        if "=" in word and not word.startswith(("-", "=")) and word.split("=", 1)[0].isidentifier():
            i += 1
        elif word in PREFIX_COMMANDS:
            i += 1
            while i < len(words) and words[i].startswith("-"):  # sudo -u user などのオプション
                i += 1
        else:
            break
    return words[i:]


def has_in_place(name: str, args: list[str]) -> bool:
    """sed -i・perl -pi・clang-format -i のように、その場で書き換えるオプションがあるか。"""
    for arg in args:
        if arg == "--in-place" or arg.startswith("--in-place="):
            return True
        if arg.startswith("-") and not arg.startswith("--"):
            letters = ""
            for ch in arg[1:]:
                if not ch.isalpha():
                    break
                letters += ch
            if name == "clang-format" and arg == "-i":
                return True
            if name in ("sed", "perl") and "i" in letters:
                return True
    return False


def is_recursive(args: list[str]) -> bool:
    return any(
        a in ("-r", "-R", "--recursive")
        or (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a))
        for a in args
    )


FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
MODIFYING_TOOLS = (
    WRITING_COMMANDS | REMOVING_COMMANDS | MODE_COMMANDS | COPY_COMMANDS | IN_PLACE_COMMANDS
)


def next_option(args: list[str]) -> int:
    """find の引数で、最初の「-」で始まる式の位置(それより前が探す場所)。"""
    for i, arg in enumerate(args):
        if arg.startswith("-") or arg in ("(", "!"):
            return i
    return len(args)


def find_modifies(args: list[str]) -> bool:
    """find が -delete か、ファイルを変えるコマンドを -exec するか。"""
    if "-delete" in args:
        return True
    for i, arg in enumerate(args):
        if arg in FIND_EXEC and i + 1 < len(args):
            tool = os.path.basename(args[i + 1])
            if tool in MODIFYING_TOOLS and (
                tool not in IN_PLACE_COMMANDS or has_in_place(tool, args[i + 2 :])
            ):
                return True
    return False


def git_reason(args: list[str]) -> str | None:
    """作業中の変更を消してしまう git コマンドなら、その名前を返す。"""
    i = 0
    while i < len(args) and args[i].startswith("-"):  # git -C dir … などのグローバルオプション
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1 :]
    if sub in DESTRUCTIVE_GIT:
        return f"git {sub}"
    if sub == "reset" and any(a in ("--hard", "--merge", "--keep") for a in rest):
        return "git reset --hard"
    if sub == "checkout" and any(a in ("--", ".", "-f", "--force") for a in rest):
        return "git checkout(ファイルを上書きする使い方)"
    if sub == "switch" and any(a in ("-f", "--force", "--discard-changes") for a in rest):
        return "git switch --force"
    return None


def bash_reason(command: str, project_dir: str, start_cwd: str) -> str | None:
    """守る場所を書き換えそうなら、その理由を返す。問題なければ None。"""
    roots = protected_roots(project_dir)
    cwd = start_cwd
    for words in split_commands(command):
        # リダイレクトの書き込み先(> file、>> file、&> file)
        for i, word in enumerate(words):
            if word in WRITE_REDIRECTS and i + 1 < len(words) and touches(words[i + 1], cwd, roots):
                return f"リダイレクト({word})で {words[i + 1]} に書き込もうとしています"
        cleaned: list[str] = []
        skip = False
        for word in words:
            if skip:
                skip = False
                continue
            if word in WRITE_REDIRECTS or word in ("<", "<<", "<<<", ">&", "<&"):
                skip = True  # リダイレクトとその対象は引数ではない
                continue
            cleaned.append(word)
        body = strip_prefixes(cleaned)
        if not body:
            continue
        name = os.path.basename(body[0])
        args = body[1:]
        operands = [a for a in args if not a.startswith("-")]

        if name == "cd":
            target = operands[0] if operands else "~"
            cwd = _resolve(target, cwd)
            continue
        if name == "git":
            reason = git_reason(args)
            if reason:
                return f"{reason} は、まだコミットしていない変更を消すことがあります"
            continue
        if name == "patch":
            return "patch でファイルを書き換えようとしています"
        if name in WRITING_COMMANDS and any(touches(a, cwd, roots) for a in operands):
            return f"{name} で守る場所のファイルを変えようとしています"
        if name in REMOVING_COMMANDS:
            # mv は親フォルダを動かしても中身ごと動く。rm は -r のときだけ親フォルダごと消える
            ancestors = name == "mv" or (name == "rm" and is_recursive(args))
            if any(touches(a, cwd, roots, include_ancestors=ancestors) for a in operands):
                return f"{name} で守る場所のファイル(またはそれを含むフォルダ)を消す・動かそうとしています"
        if name in MODE_COMMANDS and any(
            touches(a, cwd, roots, include_ancestors=is_recursive(args)) for a in operands
        ):
            return f"{name} で守る場所の権限を変えようとしています"
        if name in COPY_COMMANDS:
            destination_flags = ("-t", "--target-directory")
            for j, a in enumerate(args):
                if (
                    a in destination_flags
                    and j + 1 < len(args)
                    and touches(args[j + 1], cwd, roots)
                ):
                    return f"{name} で守る場所にファイルを置こうとしています"
                if a.startswith("--target-directory=") and touches(a.split("=", 1)[1], cwd, roots):
                    return f"{name} で守る場所にファイルを置こうとしています"
            deleting = name == "rsync" and any(a.startswith("--delete") for a in args)
            if operands and touches(operands[-1], cwd, roots, include_ancestors=deleting):
                return f"{name} で守る場所にファイルを置こうとしています"
        if (
            name in IN_PLACE_COMMANDS
            and has_in_place(name, args)
            and any(touches(a, cwd, roots) for a in operands)
        ):
            return f"{name} で守る場所のファイルをその場で書き換えようとしています"
        if name == "dd" and any(a.startswith("of=") and touches(a[3:], cwd, roots) for a in args):
            return "dd で守る場所に書き込もうとしています"
        if name == "find" and find_modifies(args):
            search_paths = [a for a in args[: next_option(args)] if not a.startswith("-")] or ["."]
            if any(touches(a, cwd, roots, include_ancestors=True) for a in search_paths):
                return "find -delete / -exec で守る場所のファイルを変えようとしています"

    # xargs やスクリプトの中で書き換えるパターン(守る場所のパスがコマンドのどこかに出てくるときだけ)
    mentions = any(rel in command for rel in PROTECTED_DIRS) or any(
        root in command for root in roots
    )
    if mentions and "xargs" in command:
        tools = ("rm", "mv", "cp", "tee", "sed", "truncate", "shred", "perl", "clang-format")
        if any(f"xargs {t}" in command or f" {t} " in command for t in tools):
            return "xargs で守る場所のファイルを変えようとしています"
    writes = (
        "write_text",
        "write_bytes",
        "unlink(",
        "rmtree",
        "os.remove",
        "os.rename",
        "os.replace",
    )
    modes = ("'w'", '"w"', "'a'", '"a"', "'wb'", '"wb"', "'w+'", '"w+"', "'x'", '"x"')
    if mentions and (
        any(w in command for w in writes)
        or ("open(" in command and any(m in command for m in modes))
    ):
        return "スクリプトで守る場所のファイルを書き換えようとしています"
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    cwd = data.get("cwd") or project_dir

    reason: str | None = None
    if tool_name == "Bash":
        reason = bash_reason(str(tool_input.get("command", "")), project_dir, cwd)
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if path and touches(str(path), cwd, protected_roots(project_dir)):
            reason = f"{path} に書き込もうとしています"

    if reason:
        print(
            f"ブロック:{reason}。engine/cpp と engine/cuda は開発者が自分で書く計算コアなので、"
            "このエージェントは変更できません(CLAUDE.md の役割分担)。"
            "直し方は文章(方針・ヒント)で伝え、テストは tests/ に置いてください。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
