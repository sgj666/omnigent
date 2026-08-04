from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from omnigent.cli import cli
from omnigent.integration_daemon import DaemonRecord


def test_feishu_missing_package_hint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    with mock.patch("omnigent.cli._feishu_installed", return_value=False):
        result = CliRunner().invoke(cli, ["integration", "feishu"])
    assert result.exit_code != 0
    assert "omnigent-feishu" in result.output
    assert "--extra feishu" in result.output


def test_feishu_background_status_stop_and_argv(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    record = DaemonRecord(123, str(tmp_path / "feishu.log"), 1)
    daemon = mock.Mock()
    daemon.running_record.side_effect = [None, record, record]
    daemon.start.return_value = record
    daemon.confirm_alive.return_value = True
    daemon.stop.return_value = record
    with (
        mock.patch("omnigent.cli._feishu_installed", return_value=True),
        mock.patch("omnigent.cli._feishu_daemon", return_value=daemon),
    ):
        runner = CliRunner()
        assert runner.invoke(cli, ["integration", "feishu", "--background"]).exit_code == 0
        assert runner.invoke(cli, ["integration", "feishu", "status"]).exit_code == 0
        assert runner.invoke(cli, ["integration", "feishu", "stop"]).exit_code == 0
    argv = daemon.start.call_args.args[0]
    assert argv[1:] == ["-m", "omnigent_feishu"]
