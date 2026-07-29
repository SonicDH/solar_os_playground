# SolarOS Playground

Community Python and Lua applications for SolarOS.

Applications live under `apps/`, carry their own `manifest.json`, and are
grouped into the categories declared by `categories.json`. The generated
`dist/catalog.json` and `.sopkg` archives are consumed by the native SolarOS
`playground` application.

See [the manifest reference](docs/manifest.md) for the complete field,
capability, and size contract.

## Add an application

1. Copy one of the existing application directories.
2. Choose a unique lowercase `id`.
3. Set `runtime` to `python` or `lua`.
4. Put the entry script and optional assets beside `manifest.json`.
5. Run:

   ```sh
   python3 scripts/build_catalog.py
   python3 -m unittest discover -s tests
   ```

6. Commit the application source and regenerated `dist/` output.

`.sopkg` files are ordinary deterministic ZIP archives. Downloaded scripts run
with the normal SolarOS Python or Lua permissions; repository maintainers must
review contributions accordingly.

## Repository URL

SolarOS uses:

```text
https://raw.githubusercontent.com/nilseuropa/solar_os_playground/main/dist/catalog.json
```

Forks can generate the same layout and be selected as an alternative source.
