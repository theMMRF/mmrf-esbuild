from pathlib import Path
from unittest import mock

from esbuild import utils


def test_get_commit_hash_runs_from_repository_root(monkeypatch) -> None:
    monkeypatch.delenv("GIT_COMMIT_HASH", raising=False)
    utils.ReleaseHelper.get_commit_hash.cache_clear()

    try:
        with mock.patch.object(
            utils.subprocess,
            "check_output",
            return_value=b"test-commit\n",
        ) as check_output:
            result = utils.ReleaseHelper.get_commit_hash()

        assert result == "test-commit"
        check_output.assert_called_once_with(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(utils.__file__).resolve().parents[2],
        )
    finally:
        utils.ReleaseHelper.get_commit_hash.cache_clear()
