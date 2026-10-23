"""サブエージェントが engine/cpp・engine/cuda を書き換えないようにするフック(.claude/hooks/protect-engine-core.py)のテスト。

開発者が自分で書く計算コアを守るための安全網なので、止めるべきコマンドを止めることと、
答え合わせ・ビルド・読むだけのコマンドを止めない(テスト担当の仕事を邪魔しない)ことの両方を確かめる。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "protect-engine-core.py"

spec = importlib.util.spec_from_file_location("protect_engine_core", HOOK)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for rel in (
        "engine/cpp/src",
        "engine/cuda",
        "engine/cpp_extra",
        "engine/reference",
        "tests/cpp",
        "build",
    ):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "engine/cpp/src/a.cpp").write_text("int main() {}\n")
    os.symlink(tmp_path / "engine/cpp", tmp_path / "lnk")
    return tmp_path.resolve()


BLOCKED = [
    "echo x > engine/cpp/a.txt",
    "echo x>engine/cpp/a.txt",
    "echo x >> engine/cuda/kernel.cu",
    "cat <<'EOF' > engine/cuda/k.cu\n__global__ void k() {}\nEOF",
    "tee engine/cpp/log.txt",
    "printf x | tee -a engine/cpp/out.txt",
    "sed -i 's/a/b/' engine/cpp/src/a.cpp",
    "sed -i.bak 's/a/b/' engine/cpp/src/a.cpp",
    "perl -pi -e 's/a/b/' engine/cpp/src/a.cpp",
    "clang-format -i engine/cpp/src/a.cpp",
    "cp tests/x.cpp engine/cpp/src/x.cpp",
    "cp -t engine/cpp/src tests/x.cpp",
    "install -m 644 tests/x.cpp engine/cpp/src/",
    "mv engine/cpp/src/a.cpp /tmp/a.cpp",
    "mv engine engine_old",
    "rm engine/cpp/src/a.cpp",
    "rm -rf engine",
    "rm -rf ./*",
    "rm -r engine/cuda",
    "cd engine/cpp && rm src/a.cpp",
    "cd engine && rm -r cpp",
    "touch engine/cpp/new.cpp",
    "mkdir -p engine/cpp/include",
    "chmod -R 000 engine",
    "find engine/cpp -name '*.o' -delete",
    "find . -name '*.cpp' -exec rm {} +",
    "find engine -name '*.cpp' -exec sed -i 's/a/b/' {} +",
    "dd if=/dev/zero of=engine/cpp/a bs=1 count=1",
    "rsync -a --delete src/ engine/",
    "sudo rm engine/cpp/src/a.cpp",
    "FOO=1 rm engine/cpp/src/a.cpp",
    "env -i rm engine/cpp/src/a.cpp",
    "rm lnk/src/a.cpp",
    "ls engine/cpp | xargs rm",
    "python3 -c \"open('engine/cpp/a.cpp', 'w').write('x')\"",
    "python3 -c \"import pathlib; pathlib.Path('engine/cpp/a.cpp').write_text('x')\"",
    "patch -p1 < fix.diff",
    "git checkout -- .",
    "git checkout -- engine/cpp/src/a.cpp",
    "git reset --hard HEAD",
    "git stash",
    "git stash push -m wip",
    "git clean -fd",
    "git restore engine/cpp/src/a.cpp",
    "git apply fix.diff",
    "git -C . reset --hard",
    "make test && git checkout .",
]

ALLOWED = [
    "ls engine/cpp",
    "cat engine/cpp/src/a.cpp",
    "sed -n 1,20p engine/cpp/src/a.cpp",
    "grep -rn main engine/cpp",
    "cmake --build build",
    "ctest --test-dir build --output-on-failure",
    "./build/engine/cpp/backtest_cli tests/golden/cases/h01_round_trip/input build/case-out",
    "rm -rf build/case-out",
    "make cpp-case CASE=h01_round_trip 2>&1 | tail -20",
    "BACKTEST_CPP_STAGE=1 uv run pytest tests/python/test_golden.py -k cpp -v",
    "git diff engine/cpp",
    "git log --oneline -5 -- engine/cpp",
    "git status",
    "git checkout -b test/add-cases",
    "git show HEAD:engine/cpp/src/a.cpp",
    "find . -name '*.cpp' -exec grep -l main {} +",
    "find engine/cpp -name '*.cpp'",
    "rm *.txt",
    "cp engine/cpp/src/a.cpp /tmp/a.cpp",
    "clang-format --dry-run engine/cpp/src/a.cpp",
    "echo x > tests/cpp/notes.txt",
    "echo x > /dev/null",
    "touch engine/cpp_extra/a.cpp",
    "mkdir -p tests/cpp/fixtures",
    "python3 -c \"print(open('engine/cpp/src/a.cpp').read())\"",
    "uv run python -m engine.reference.cli tests/golden/cases/h01_round_trip/input build/out",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_commands_that_change_the_engine_core(project: Path, command: str) -> None:
    assert hook.bash_reason(command, str(project), str(project)) is not None


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_reading_building_and_testing(project: Path, command: str) -> None:
    assert hook.bash_reason(command, str(project), str(project)) is None


def test_relative_paths_follow_the_current_directory(project: Path) -> None:
    cwd = str(project / "engine")
    assert hook.bash_reason("rm cpp/src/a.cpp", str(project), cwd) is not None
    assert hook.bash_reason("rm reference/x.py", str(project), cwd) is None


def run_hook(project: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        timeout=30,
    )


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_file_tools_are_blocked_inside_the_core(project: Path, tool: str) -> None:
    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": str(project / "engine/cpp/src/a.cpp")},
        "cwd": str(project),
    }
    completed = run_hook(project, payload)
    assert completed.returncode == 2
    assert "ブロック" in completed.stderr and "役割分担" in completed.stderr


def test_notebook_edit_is_blocked_inside_the_core(project: Path) -> None:
    payload = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": str(project / "engine/cuda/try.ipynb")},
        "cwd": str(project),
    }
    assert run_hook(project, payload).returncode == 2


def test_file_tools_are_allowed_elsewhere(project: Path) -> None:
    for path in ("tests/python/test_new.py", "engine/cpp_extra/a.cpp", "docs/benchmarks.md"):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(project / path)},
            "cwd": str(project),
        }
        assert run_hook(project, payload).returncode == 0, path


def test_bash_through_main(project: Path) -> None:
    blocked = {"tool_name": "Bash", "tool_input": {"command": "rm -rf engine"}, "cwd": str(project)}
    allowed = {"tool_name": "Bash", "tool_input": {"command": "make test"}, "cwd": str(project)}
    assert run_hook(project, blocked).returncode == 2
    assert run_hook(project, allowed).returncode == 0


def test_broken_input_does_not_block(project: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0
