"""Tab completion: `completion bash|zsh|fish` prints a script made from the parser itself.

The bash script is run for real where bash exists, the way bash calls it while you type. zsh and
fish are checked for syntax where they are installed.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from parro import cli, completion

PROGRAM = "parro-client"
# On Windows, "bash" may be the WSL launcher, which has no Linux to start on a test machine.
BASH = shutil.which("bash") if os.name != "nt" else None
ZSH = shutil.which("zsh")
FISH = shutil.which("fish")


def script(shell: str) -> str:
    return completion.script(shell, PROGRAM, cli.build_parser())


def complete(line: str, folder: Path | None = None) -> list[str]:
    """What bash offers after `line` (a trailing space means a new, empty word)."""
    assert BASH is not None
    typed = line.split(" ")
    words_array = " ".join(f"'{word}'" for word in typed)
    program = (
        f"{script('bash')}\n"
        f"COMP_WORDS=({words_array}); COMP_CWORD={len(typed) - 1}\n"
        f"_parro_client_complete\n"
        'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    done = subprocess.run(
        [BASH, "--norc", "--noprofile", "-c", program],
        capture_output=True,
        text=True,
        check=True,
        cwd=folder,
    )
    return [line for line in done.stdout.splitlines() if line]


def test_every_command_is_in_every_script():
    _options, commands = completion.describe(cli.build_parser())
    names = {command.name for command in commands}
    assert {"announcements", "rsvp", "attachment", "completion"} <= names
    assert names == set(cli.HANDLERS) | {"completion"}
    for shell in completion.SHELLS:
        made = script(shell)
        assert all(name in made for name in names), shell


def test_the_command_needs_no_login_and_sends_nothing(capsys):
    def no_client(_settings: object) -> object:
        raise AssertionError("completion must not make a client")

    assert cli.main(["completion", "bash"], make_client=no_client) == 0  # type: ignore[arg-type]
    assert "complete -F" in capsys.readouterr().out


def test_an_unknown_shell_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["completion", "tcsh"])
    assert stopped.value.code == 2


def test_only_plain_words_reach_a_script():
    with pytest.raises(ValueError):
        completion.words(["fine", "$(rm -rf ~)"])


def test_fish_help_texts_are_short_and_quoted():
    assert completion.one_line("Don't. Second sentence.") == "Don\\'t"
    assert len(completion.one_line("x" * 200)) <= 70


needs_bash = pytest.mark.skipif(BASH is None, reason="bash is not installed")


@needs_bash
def test_bash_completes_commands():
    offered = complete(f"{PROGRAM} ann")
    assert offered == ["announcements", "announcement"]


@needs_bash
def test_bash_completes_global_options_before_a_command():
    assert "--format" in complete(f"{PROGRAM} --fo")


@needs_bash
def test_bash_completes_the_values_of_an_option():
    assert complete(f"{PROGRAM} --format ") == ["auto", "json", "markdown"]


@needs_bash
def test_bash_skips_an_option_s_value_when_finding_the_command():
    assert complete(f"{PROGRAM} --format json ann") == ["announcements", "announcement"]


@needs_bash
def test_bash_completes_a_fixed_first_argument_once():
    assert complete(f"{PROGRAM} rsvp ") == ["accept", "decline", "tentative"]
    assert complete(f"{PROGRAM} rsvp accept ") == []


@needs_bash
def test_bash_completes_a_command_s_options():
    offered = complete(f"{PROGRAM} calendar --")
    assert "--details" in offered and "--format" in offered


@needs_bash
def test_bash_completes_file_names_where_a_folder_is_asked(tmp_path):
    (tmp_path / "downloads").mkdir()
    assert complete(f"{PROGRAM} attachment 1 --save-to dow", tmp_path) == ["downloads"]


@needs_bash
def test_bash_offers_nothing_for_an_id():
    assert complete(f"{PROGRAM} announcements --limit ") == []


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_the_zsh_script_loads(tmp_path):
    assert ZSH is not None
    path = tmp_path / "completion.zsh"
    path.write_text(script("zsh"), encoding="utf-8")
    subprocess.run([ZSH, "-f", "-c", f"source {path}"], check=True, cwd=tmp_path)


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_the_fish_script_works(tmp_path):
    assert FISH is not None
    path = tmp_path / "completion.fish"
    path.write_text(script("fish"), encoding="utf-8")
    subprocess.run([FISH, "--no-execute", str(path)], check=True)
    done = subprocess.run(
        [FISH, "-c", f"source {path}; complete -C '{PROGRAM} rsvp '"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert {"accept", "decline", "tentative"} <= {
        line.split("\t")[0] for line in done.stdout.splitlines()
    }
