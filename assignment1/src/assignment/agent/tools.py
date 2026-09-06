"""Tool definitions exposed to the model, in the OpenAI tool-calling format."""

EXECUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute",
        "description": (
            "Run a bash command and return its stdout, stderr, and exit code. "
            "A non-zero exit code is reported, not raised.\n"
            "\n"
            "Every command runs in a new subshell, so a `cd` or an export does not "
            "carry over to the next command. Use the `cwd` and `env` arguments "
            "instead. Files you write do persist.\n"
            "\n"
            "Commands are non-interactive and cannot prompt for input, so pass "
            "flags like `-y` where a command would otherwise ask for confirmation. "
            "Prefer commands that produce little output; when reading a file, use "
            "`head`, `tail`, or `sed -n '10,20p'` rather than printing all of it.\n"
            "\n"
            "Useful patterns:\n"
            "- Create a file: `cat <<'EOF' > newfile.py` ... `EOF`\n"
            "- Edit in place: `sed -i 's/old/new/g' filename.py` (drop the trailing "
            "`g` to replace only the first match; restrict to a line range with "
            "`sed -i '1,10s/old/new/g'`)\n"
            "- View numbered lines: `nl -ba filename.py | sed -n '10,20p'`"
        ),
        # The nested env object intentionally accepts arbitrary variable names,
        # which is incompatible with strict schemas on some providers.
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "anyOf": [
                        {
                            "type": "string",
                            "description": 'A shell command line, e.g. "ls -la | head".',
                        },
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                'The command as an argv list, e.g. ["ls", "-la"]. '
                                "Use this with shell=false when arguments contain "
                                "characters the shell would interpret."
                            ),
                        },
                    ],
                    "description": "The command to run.",
                },
                "shell": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Whether to run the command through a shell, which enables "
                        "pipes, redirection, and globbing. Defaults to true. Set to "
                        "false when passing an argv list."
                    ),
                },
                "cwd": {
                    "type": ["string", "null"],
                    "description": (
                        "Absolute path to run the command in. Defaults to the "
                        "sandbox's current working directory."
                    ),
                },
                "timeout": {
                    "type": ["number", "null"],
                    "description": (
                        "Seconds to allow the command to run before killing it. "
                        "Defaults to no timeout."
                    ),
                },
                "env": {
                    "type": ["object", "null"],
                    "additionalProperties": {"type": "string"},
                    "description": "Extra environment variables to set for this command.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

SEND_MESSAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_message",
        "description": ("Send a message to the user."),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": ("Content of the message"),
                },
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
}

INVOKE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "invoke_skill",
        "description": (
            "Load a skill and return its instructions. A skill is a short guide "
            "for one kind of work, written ahead of time.\n"
            "\n"
            "Call this before starting work a skill covers, and follow what it "
            "says in place of your default approach."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "The skill's directory name, for example `hello-skill`."
                    ),
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}

PLAY_MOVE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "play_move",
        "description": (
            "Play one move as White in the live game. `move` uses UCI notation, "
            "for example `e2e4` or `e7e8q` (promotion includes the piece suffix). "
            "The server applies Black's reply automatically, so submit only "
            "White's move and inspect the returned board for the next move."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "move": {
                    "type": "string",
                    "description": "A chess move in UCI notation, e.g. e2e4.",
                },
            },
            "required": ["move"],
            "additionalProperties": False,
        },
    },
}

SIMULATE_MOVE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "simulate_move",
        "description": (
            "Inspect a position from a six-field FEN, or apply exactly one ply "
            "without changing the live game. Pass only a `fen` to read that "
            "position and its legal moves; add a UCI `move` to step one ply for "
            "either side. Returns JSON with `fen`, `squares`, `turn`, "
            "`legal_moves`, and terminal-result fields. Never touches the real "
            "board or invokes the opponent."
        ),
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "fen": {
                    "type": "string",
                    "description": (
                        "A complete six-field FEN of the position to inspect or "
                        "step from."
                    ),
                },
                "move": {
                    "type": ["string", "null"],
                    "description": "Optional UCI move to apply, e.g. e2e4.",
                },
            },
            "required": ["fen"],
            "additionalProperties": False,
        },
    },
}

RUN_PYTHON_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Execute a Python snippet in the sandbox beside the chess server. "
            "The functions `simulate_move(fen, move=None)` and `play_move(move)` "
            "are already defined and callable inside the snippet, so write code "
            "that calls simulate_move to explore lines, then calls play_move "
            "once to commit the chosen move. Write only the snippet body, no "
            "import lines. Returns the snippet's stdout."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to run in the sandbox.",
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}
