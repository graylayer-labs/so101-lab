# Projects

One folder per project. Each one is its own uv workspace package and can
depend on the shared `so101` package.

```
projects/<name>/
├── pyproject.toml   # depends on so101 through the workspace
├── README.md        # Goal, Expected results, Status
├── src/<name>/      # code
├── tests/           # tests
└── configs/         # run configs for this project
```

## Adding a project

1. Copy the template: `cp -R projects/_template projects/<name>`.
2. Rename the package: in `pyproject.toml` set `name = "<name>"` and
   `packages = ["src/<name_underscored>"]`, then
   `mv src/my_project src/<name_underscored>` and fix the import in
   `tests/test_smoke.py`.
3. Fill in the README: Goal and Expected results before writing code.
4. `uv sync --dev --all-packages`, then `uv run pytest` and commit, including
   the updated `uv.lock`.
5. Add the project to the table below and an entry to `docs/progress.md`.

Third-party dependencies (LeRobot, torch, and so on) go in the project's own
`pyproject.toml`, added with `uv add --package <name> <dependency>`.

## Projects

| Project | Goal | Status |
|---|---|---|
| [act-policy](act-policy/) | Train and run an ACT policy on the follower | `so101-train` done; smoke run next |
