# my-project

<What this project does with the arm, in two sentences.>

## Goal

<What is true when this project is done.>

## Expected results

<Written down before the first run: what you expect to see, and the number
that would count as success or failure.>

## Status (YYYY-MM-DD)

- Done: <...>
- Doing: <...>
- Next: <...>

## Layout

- `src/my_project/`: the code.
- `tests/`: tests for it.
- `configs/`: run configs for this project. Machine settings (ports, cameras)
  stay in the root `configs/`.

## Run

```bash
uv sync --dev --all-packages
uv run pytest projects/my-project
```
