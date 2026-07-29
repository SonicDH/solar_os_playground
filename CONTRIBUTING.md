# Contributing

Add or change an application in its own directory under `apps/`. Keep generated
files reproducible and include documentation useful to someone browsing the
repository before installation.

Before opening a pull request, run:

```sh
python3 scripts/build_catalog.py
python3 -m unittest discover -s tests
git diff --check
```

Commit the application source and the regenerated `dist/` files together.
Reviewers should inspect scripts as executable code: SolarOS verifies package
integrity during download, but Playground applications are not sandboxed.

See [the manifest reference](docs/manifest.md) for the catalog contract.
