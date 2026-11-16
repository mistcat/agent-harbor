from pathlib import Path

import pytest

from agent_panel.cli import main, parse_args


def test_help_exits_zero():
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0


def test_parses_session_and_cwd():
    ns = parse_args(["--session", "abc", "--cwd", "/x"])
    assert ns.session == "abc"
    assert ns.cwd == Path("/x")


def test_no_sound_flag():
    assert parse_args(["--no-sound"]).no_sound is True
    assert parse_args([]).no_sound is False


def test_config_dir_flag():
    assert parse_args(["--config-dir", "/cfg"]).config_dir == Path("/cfg")
    assert parse_args([]).config_dir is None


def test_keep_done_flag():
    assert parse_args(["--keep-done", "30"]).keep_done == 30
    assert parse_args([]).keep_done == 180


def test_attention_sound_flag():
    assert parse_args([]).attention_sound == "boom"
    assert parse_args(["--attention-sound", "say"]).attention_sound == "say"
    assert parse_args(["--attention-sound", "off"]).attention_sound == "off"
    assert parse_args(["--attention-sound", "ahoy"]).attention_sound == "ahoy"
    with pytest.raises(SystemExit):
        parse_args(["--attention-sound", "loud"])


def test_also_repo_flag_repeats():
    assert parse_args([]).also_repo == []
    assert parse_args(["--also-repo", "/a", "--also-repo", "/b"]).also_repo == [Path("/a"), Path("/b")]
