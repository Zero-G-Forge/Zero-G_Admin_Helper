# Examples/ZGB_Portal

Example (not live) data for the ZeroGBridge Portal (View > ZeroGBridge Portal).

The portal reads these files through `SampleDataSource` in
`features/dashboard/zgb_portal/data_source.py`. When the live source is added,
it will read from ZAH's bridge connection instead and these files stay as examples.

- `loader_state.json` — LOADER tab: server name, loader/core versions, port, players online, reload history.
- `cores/` — placeholder core DLLs (text files). `1.4.3` fails its self-test, `1.4.4` passes.
- `scripts/` — example IronPython 3.4 scripts for the BRIDGE tab, plus `scripts.json` (hook, enabled, time limit, live).

Nothing here is sent to a game server.
