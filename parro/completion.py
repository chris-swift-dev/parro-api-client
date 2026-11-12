"""Tab completion for the command line: `parro-client completion bash|zsh|fish` prints a script.

The script is made from the CLI's own argparse parser, so it always matches the commands and
options of this version. It completes commands, options, the values of options with a fixed set
(`--format markdown`), the first argument where that is a fixed set (`rsvp accept`), and file
names after options that take a file or a folder. It never runs the client while you type, so
completing sends nothing to Parro and needs no login.

Standard library only.
"""

import argparse
import re
from dataclasses import dataclass, field

SHELLS = ("bash", "zsh", "fish")
PATH_METAVARS = frozenset({"DIR", "FILE", "PATH"})
SAFE_WORD = re.compile(r"^[A-Za-z0-9_./:=+-]+$")


@dataclass
class Option:
    flags: list[str]
    help: str
    takes_value: bool
    choices: list[str] = field(default_factory=list)
    is_path: bool = False


@dataclass
class Command:
    name: str
    help: str
    options: list[Option]
    first_argument: list[str]  # the choices of the first positional argument, if fixed


def describe_option(action: argparse.Action) -> Option:
    takes_value = action.nargs != 0
    choices = [str(choice) for choice in action.choices or []] if takes_value else []
    return Option(
        flags=list(action.option_strings),
        help=action.help if isinstance(action.help, str) else "",
        takes_value=takes_value,
        choices=choices,
        is_path=takes_value and str(action.metavar or "") in PATH_METAVARS,
    )


def options_of(parser: argparse.ArgumentParser) -> list[Option]:
    return [
        describe_option(action)
        for action in parser._actions
        if action.option_strings and action.help != argparse.SUPPRESS
    ]


def first_argument_of(parser: argparse.ArgumentParser) -> list[str]:
    for action in parser._actions:
        if not action.option_strings:
            return [str(choice) for choice in action.choices or []]
    return []


def describe(parser: argparse.ArgumentParser) -> tuple[list[Option], list[Command]]:
    """The global options and every command, read from the parser."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            commands = [
                Command(
                    name,
                    str(helps.get(name, "")),
                    options_of(sub),
                    first_argument_of(sub),
                )
                for name, sub in action.choices.items()
            ]
            return options_of(parser), commands
    return options_of(parser), []


def words(values: list[str]) -> str:
    """A space-separated list for a shell script. Only plain words: nothing to quote or expand."""
    for value in values:
        if not SAFE_WORD.match(value):
            raise ValueError(f"not a plain word: {value!r}")
    return " ".join(values)


def one_line(text: str) -> str:
    """A short help text for fish, inside single quotes: the first sentence, on one line."""
    short = " ".join(text.split()).split(". ")[0].rstrip(".")
    if len(short) > 70:
        short = short[:69].rstrip() + "…"
    return short.replace("\\", "\\\\").replace("'", "\\'")


# ------------------------------------------------------------------------------ bash and zsh


def bash_script(program: str, parser: argparse.ArgumentParser) -> str:
    global_options, commands = describe(parser)
    function = "_" + re.sub(r"\W", "_", program) + "_complete"
    command_cases = []
    for command in commands:
        flags = [flag for option in command.options for flag in option.flags]
        command_cases.append(
            f"        {command.name}) options='{words(flags)}'; "
            f"first='{words(command.first_argument)}' ;;"
        )
    value_cases = []
    for option in [*global_options, *(o for c in commands for o in c.options)]:
        if not option.takes_value:
            continue
        pattern = "|".join(option.flags)
        if option.choices:
            action = f"COMPREPLY=($(compgen -W '{words(option.choices)}' -- \"$cur\")); return"
        elif option.is_path:
            action = 'COMPREPLY=($(compgen -f -- "$cur")); return'
        else:
            action = "return"
        case = f"        {pattern}) {action} ;;"
        if case not in value_cases:
            value_cases.append(case)
    global_flags = [flag for option in global_options for flag in option.flags]
    every_option = [*global_options, *(o for c in commands for o in c.options)]
    value_flags = sorted({flag for o in every_option if o.takes_value for flag in o.flags})
    value_block = "\n".join(value_cases)
    command_block = "\n".join(command_cases)
    command_names = words([c.name for c in commands])
    return f"""# {program} tab completion for bash (made by `{program} completion bash`)
{function}() {{
    local cur prev command="" options="" first="" index arguments=0
    local takes_value=' {words(value_flags)} '
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "$prev" in
{value_block}
    esac
    for ((index = 1; index < COMP_CWORD; index++)); do
        case "${{COMP_WORDS[index]}}" in
            -*) [[ "$takes_value" == *" ${{COMP_WORDS[index]}} "* ]] && index=$((index + 1)) ;;
            *) if [[ -z "$command" ]]; then command="${{COMP_WORDS[index]}}";
               else arguments=$((arguments + 1)); fi ;;
        esac
    done
    if [[ -z "$command" ]]; then
        if [[ "$cur" == -* ]]; then
            COMPREPLY=($(compgen -W '{words(global_flags)}' -- "$cur"))
        else
            COMPREPLY=($(compgen -W '{command_names}' -- "$cur"))
        fi
        return
    fi
    case "$command" in
{command_block}
    esac
    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$options" -- "$cur"))
    elif [[ $arguments -eq 0 && -n "$first" ]]; then
        COMPREPLY=($(compgen -W "$first" -- "$cur"))
    fi
}}
complete -F {function} {program}
"""


def zsh_script(program: str, parser: argparse.ArgumentParser) -> str:
    """zsh runs the bash function through its bashcompinit layer, so both behave the same."""
    return f"""# {program} tab completion for zsh (made by `{program} completion zsh`)
autoload -U +X compinit && compinit
autoload -U +X bashcompinit && bashcompinit
{bash_script(program, parser)}"""


# ------------------------------------------------------------------------------------- fish


def fish_option(program: str, condition: str, option: Option) -> str:
    parts = [f"complete -c {program} -n '{condition}'"]
    for flag in option.flags:
        if flag.startswith("--"):
            parts.append(f"-l {flag[2:]}")
        else:
            parts.append(f"-s {flag[1:]}")
    if option.choices:
        parts.append(f"-x -a '{words(option.choices)}'")
    elif option.is_path:
        parts.append("-r -F")
    elif option.takes_value:
        parts.append("-x")
    if option.help:
        parts.append(f"-d '{one_line(option.help)}'")
    return " ".join(parts)


def fish_script(program: str, parser: argparse.ArgumentParser) -> str:
    global_options, commands = describe(parser)
    lines = [
        f"# {program} tab completion for fish (made by `{program} completion fish`)",
        f"complete -c {program} -f",
    ]
    lines += [fish_option(program, "__fish_use_subcommand", o) for o in global_options]
    for command in commands:
        lines.append(
            f"complete -c {program} -n '__fish_use_subcommand' -a {words([command.name])} "
            f"-d '{one_line(command.help)}'"
        )
        seen = f"__fish_seen_subcommand_from {command.name}"
        lines += [fish_option(program, seen, option) for option in command.options]
        if command.first_argument:
            lines.append(f"complete -c {program} -n '{seen}' -a '{words(command.first_argument)}'")
    return "\n".join(lines) + "\n"


def script(shell: str, program: str, parser: argparse.ArgumentParser) -> str:
    if shell == "bash":
        return bash_script(program, parser)
    if shell == "zsh":
        return zsh_script(program, parser)
    if shell == "fish":
        return fish_script(program, parser)
    raise ValueError(f"no completion for {shell}; one of: {', '.join(SHELLS)}")
