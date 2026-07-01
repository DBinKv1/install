---
name: wuji-cli-doctor
description: Doctor skills for Wuji CLI
metadata:
  author: DBinK
  version: "1.0"
  requires:
    bins: ["wuji"]
  cliHelp: "wuji doctor --help"
---

当需要诊断设备任意故障时, 可以使用 wuji doctor 命令

目前支持检测的设备与故障类型有:

- Wuji Glove
  - EMF 断线检测
  - 触觉传感器 坏点/坏行列 检测


```bash
$ wuji doctor
✅ Environment
✅ Access

── WG1JA03260529020 ──
├─ ✅ EMF disconnect check：sampled 100 valid frames, all 5 fingers normal
└─ ✅ tactile dead-pixel check：sampled 100 valid frames: 0 dead pixels, 0 bad rows, 0 bad cols

── WG1KA06260617527 ──
├─ ✅ EMF disconnect check：sampled 100 valid frames, all 5 fingers normal
└─ ⚠️️ tactile dead-pixel check：sampled 100 valid frames: 2 dead pixels, 0 bad rows, 2 bad cols
   ├─ ⚠️️ Thumb：1 dead pixel(s)
   ├─ ⚠️️ Palm：1 dead pixel(s)
   ├─ ⚠️️ Bad col 13：col 13 exceeds bad-line threshold
   └─ ⚠️️ Bad col 15：col 15 exceeds bad-line threshold
   💡 tactile check result is for reference only; use Wuji Studio's full panel test for precision diagnosis

```