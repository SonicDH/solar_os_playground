# Control Center

Control Center is a graphical status and service manager for SolarOS. It uses
the native Python APIs introduced by current SolarOS builds; it does not run or
parse shell commands.

## Features

- Identity, uptime, registered-app count, and job count overview.
- Background-job list with active jobs first, a solid divider before inactive
  jobs, and incremental name selection as you type.
- Confirmed start and stop actions for jobs. Jobs that require command-line
  arguments can be started through sequential generic argument fields.
- Wi-Fi start/reconnect, station disconnect, and confirmed service stop.
- Storage status and capacity when the active MicroPython integer build can
  represent the volume's byte counts, plus block-device rescan and
  default-volume mounting.
- Battery voltage, charge state, external-power status, and environmental
  readings when the corresponding hardware services are present.
- Graceful handling of services unavailable in a particular firmware flavor.
- An icon-led instrument-panel layout with crisp selection outlines, compact
  page counters, and native SolarOS symbols for each main control area.
- Overview and Hardware readings use aligned, individually separated key/value
  rows rather than dense wrapped text.

Control Center deliberately does not unmount its own storage, erase saved Wi-Fi
profiles, or change the system identity. These operations are too disruptive
for a one-key dashboard action.

SolarOS currently exposes job arguments as an ordered list of strings, without
names, types, choices, or defaults. Control Center therefore adds generic fields
sequentially; enter values in the same order used by `job start <name> ...`.

## Controls

- Up/Down or `j`/`k`: move through ordinary lists. In Background jobs, use
  Up/Down so every printable key remains available for name selection.
- Type a job-name prefix in Background jobs to select the first match;
  Backspace shortens the prefix.
- Enter or Right: open or activate the selected item.
- For a stopped job, choose `y` to use defaults or `n` to enter one argument per
  field. Submit a blank field to finish and start the job.
- Escape or Left: go back or exit. In other screens, `q` also goes back.
- Page Up/Page Down: move through long job lists.
- Destructive or connection-breaking actions require `y` confirmation.

## Requirements

Control Center requires a current SolarOS Python runtime with `solaros.jobs`,
`solaros.wifi`, `solaros.storage`, `solaros.identity`, `solaros.apps`, and the
graphical display API. Unsupported optional services are shown as unavailable
instead of preventing the app from opening.
