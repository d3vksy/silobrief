# siloBrief

[한국어](README.ko.md)

siloBrief is a local command-line tool for preparing a reviewed Markdown research brief
from a Python project. It is intended for development environments where source code and
internet access are separated.

The project is in pre-release development. Its frozen v0.1 behavior is documented in
[`docs/V0_1_CONTRACT.md`](docs/V0_1_CONTRACT.md).

The current development build exposes its version command after a local install:

```console
python -m pip install .
sb --version
```

Expected output:

```text
siloBrief 0.1.0
```

## Boundaries

- Python 3.10 or newer on Windows and Ubuntu
- no runtime dependencies, network access, language model, or automatic transfer
- one request produces one Markdown file after explicit human review
- path-based exclusions do not identify sensitive names inside otherwise allowed files

siloBrief is not a security scanner, export-approval system, or guarantee against data
disclosure.

## Contributing

The project accepts changes through an Issue and a pull request to `develop`. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) before starting work.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
