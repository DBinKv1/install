---
name: wuji-cli-base
description: Base skills for Wuji CLI
metadata:
  author: DBinK
  version: "1.0"
  requires:
    bins: ["wuji"]
  cliHelp: "wuji --help"
---

在任意命令后面添加 --help 参数, 即可查看该命令的详细帮助信息, 例如:

```bash
$ wuji --help

Wuji CLI — core Wuji Studio capabilities for headless / automation / scripting scenarios

Usage: wuji [OPTIONS] <COMMAND>

Commands:
  devices      Scan / list devices
  connect      Connect to a device (supports selecting by Handedness)
  resources    List readable/writable parameters and subscribable streams of a device
  get          Read a parameter
  set          Write a parameter
  sub          Subscribe to real-time data
  doctor       Environment and device health self-check
  completions  Generate shell auto-completion script

Options:
      --json     Output as pretty-printed JSON
      --jsonl    Output as JSON Lines (one compact JSON object per frame/record)
  -h, --help     Print help
  -V, --version  Print version

$ wuji devices --help
Scan / list devices

Usage: wuji devices [OPTIONS]

Options:
      --json   Output as pretty-printed JSON
      --jsonl  Output as JSON Lines (one compact JSON object per frame/record)
  -h, --help   Print help
```

大部分命令有 --json 参数, 用于提供给 Agent 查看更详细/更结构化的信息, 不带 --json 参数时, 会以人类阅读友好的方式输出, 例如:

```bash
$ wuji devices
found 1 device(s)
┌──────────────────┬─────────────┬───────────┬──────┬─────────────────────┬─────────────────────┬──────────────────┐
│ SN               ┆ Device Type ┆ Transport ┆ Port ┆ IP                  ┆ Address             ┆ Firmware Version │
╞══════════════════╪═════════════╪═══════════╪══════╪═════════════════════╪═════════════════════╪══════════════════╡
│ WG1JA03260529020 ┆             ┆ Udp       ┆ -    ┆ 192.168.1.100:50001 ┆ 192.168.1.100:50001 ┆                  │
└──────────────────┴─────────────┴───────────┴──────┴─────────────────────┴─────────────────────┴──────────────────┘

$ wuji devices --json
{
  "devices": [
    {
      "sn": "WG1JA03260529020",
      "device_type": "",
      "transport": "Udp",
      "port": null,
      "ip": "192.168.1.100:50001",
      "address": "192.168.1.100:50001",
      "firmware_version": ""
    }
  ]
}
```

