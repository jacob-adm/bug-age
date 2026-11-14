# Contributing

## Tests

```sh
python3 -m unittest discover -s tests                          # unit, CLI, oracle and sweep tests
BUG_AGE_DOCKER_TESTS=1 python3 -m unittest discover -s tests   # adds the Docker runner test (needs the image)
```

The oracle test regenerates both example runs from clones in `work/` and compares every output
with the committed files byte for byte. The sweep tests build a toy crate, so they need cargo.

## Contributing

Changes reach `main` only through pull requests.

1. Fork the repository and create a branch.
2. Make the change, then run `python3 -m unittest discover -s tests`. If you changed bundles, results or the article, also run `make article timings`.
3. Open a pull request against `main`. CI runs the tests and the article and timing checks on Linux and macOS; all must pass before merging. Pull requests are merged with a merge commit.

Keep the rules in [Rigor rules](docs/method.md#rigor-rules): numbers come from scripts, unrun stages are NOT TESTED, and bundles stay blameless.
