# Playground manifest

Every application is one directory below `apps/`. Its directory name and
manifest `id` must match.

```json
{
  "id": "weather-station",
  "name": "Weather Station",
  "version": "1.0.0",
  "runtime": "python",
  "entry": "main.py",
  "category": "utilities",
  "description": "Shows local environmental sensor readings.",
  "author": "Contributor name",
  "min_solaros": "4.4.0",
  "tags": ["weather", "sensors"],
  "requires": ["temperature", "humidity", "gfx"]
}
```

Fields are deliberately strict:

| Field | Meaning |
| --- | --- |
| `id` | Stable lowercase identifier using letters, digits, and single dashes. |
| `name` | User-facing application name. |
| `version` | Application version in `MAJOR.MINOR.PATCH` form. |
| `runtime` | `python` or `lua`. |
| `entry` | Safe relative path to the `.py` or `.lua` entry script. |
| `category` | An ID declared by `categories.json`. |
| `description` | Short catalog and details-screen description. |
| `author` | Contributor or project name. |
| `min_solaros` | Oldest compatible SolarOS version. |
| `tags` | Search terms. |
| `requires` | Board capabilities required at runtime. |

Capability names are the same names reported by the SolarOS `board` command,
including `display`, `gfx`, `cdc`, `uart`, `sd`, `i2c`, `spi`, `rtc`,
`battery`, `audio`, `audio_input`, `wifi`, `ble`, `gpio`, `adc`, `pwm`,
`key`, `buttons`,
`joystick`, `adc_dpad`, `temperature`, `humidity`, `psram`, `status_led`,
`display_brightness`, `expansion_gpio`, `expansion_i2c`, `expansion_spi`,
`expansion_uart`, `expansion_adc`, `expansion_pwm`, and `simd`.

The generator enforces the firmware's catalog sizes and text limits, creates a
deterministic `.sopkg` ZIP, and writes its exact size and SHA-256 into
`dist/catalog.json`.

## Script command-line convention

An application that accepts one primary input file should use `--file PATH`.
This option is optional for applications that do not consume files. SolarOS
recognizes the exact `--file` token after `playground run APP-ID` and completes
filesystem paths for its following argument.

Document the option in the application's README when it is supported. No
manifest field is required; arguments after the application ID are forwarded
unchanged to Python through `sys.argv` or to Lua through `arg`.
