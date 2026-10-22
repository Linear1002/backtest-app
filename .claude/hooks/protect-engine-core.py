#!/usr/bin/env python3
"""test-runner サブエージェント用の PreToolUse フック。

engine/cpp と engine/cuda(開発者が自分で書く計算コア)への Edit/Write をブロックする。
終了コード 2 で終わると、ツール呼び出しがブロックされ、stderr が Claude に返される。
"""
import json
import os
import sys

PROTECTED_DIRS = ("engine/cpp", "engine/cuda")


def main() -> int:
    data = json.load(sys.stdin)
    file_path = data.get("tool_input", {}).get("file_path")
    if not file_path:
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", data.get("cwd", ""))
    # シンボリックリンク経由の書き込みも防ぐため、実体パスで比較する
    target = os.path.realpath(file_path)
    for rel in PROTECTED_DIRS:
        protected = os.path.realpath(os.path.join(project_dir, rel))
        if target == protected or target.startswith(protected + os.sep):
            print(
                f"ブロック: {rel} は開発者が自分で書く計算コアのため、"
                "test-runner は編集できません。テストは tests/ に置いてください。",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
