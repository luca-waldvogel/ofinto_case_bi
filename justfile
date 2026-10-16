set positional-arguments

setup:
    uv sync

app *args:
    uv run --locked ofinto "$@"

import *args:
    uv run --locked ofinto import "$@"

test *args:
    uv run --locked pytest "$@"
