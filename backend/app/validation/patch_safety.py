from __future__ import annotations

from pathlib import PurePosixPath

MAX_PATCH_BYTES = 100_000
VALID_PATCH_PATHS = {
    "services/payment_service/main.py",
    "services/order_service/main.py",
    "services/user_service/main.py",
}


def validate_patch_diff(diff: str) -> str:
    if not isinstance(diff, str) or not diff or len(diff.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("Patch is empty or exceeds the 100 KB limit.")
    if "\x00" in diff:
        raise ValueError("Patch contains invalid binary data.")

    headers = [
        line
        for line in diff.splitlines()
        if line.startswith("--- ") or line.startswith("+++ ")
    ]
    if len(headers) != 2 or not headers[0].startswith("--- a/") or not headers[1].startswith("+++ b/"):
        raise ValueError("Patch must change exactly one existing file.")

    old_path = headers[0][6:]
    new_path = headers[1][6:]
    if old_path != new_path:
        raise ValueError("Renames and multi-file patches are not allowed.")
    parsed_path = PurePosixPath(old_path)
    if (
        parsed_path.is_absolute()
        or "\\" in old_path
        or any(part in {"", ".", ".."} for part in parsed_path.parts)
        or old_path not in VALID_PATCH_PATHS
    ):
        raise ValueError("Patch target is outside the approved demo service files.")
    if any(
        marker in diff
        for marker in (
            "GIT binary patch",
            "new file mode",
            "deleted file mode",
            "old mode",
            "new mode",
            "rename from ",
            "rename to ",
            "copy from ",
            "copy to ",
        )
    ):
        raise ValueError("Binary files, file modes, additions, deletions, and renames are not allowed.")
    if not any(line.startswith("@@ ") for line in diff.splitlines()):
        raise ValueError("Patch must contain a unified-diff hunk.")
    return old_path
