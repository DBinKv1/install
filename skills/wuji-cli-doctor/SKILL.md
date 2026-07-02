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

当需要诊断设备故障时, 可以使用 `wuji doctor` 命令

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

`wuji doctor -v` 可以列出所有检查项目 (默认通过的项目不显示, 添加 -v 选项可以显示所有项目)

```bash
$ wuji doctor
✅ Environment
✅ Access

── WG1KA06260522012 ──
├─ ✅ EMF disconnect check：sampled 100 valid frames, all 5 fingers normal
└─ ⚠ tactile dead-pixel check：sampled 100 valid frames: 0 dead pixels, 0 bad rows, 1 bad cols
   └─ ⚠ Bad col 0：col 0 exceeds bad-line threshold
   💡 tactile check result is for reference only; use Wuji Studio's full panel test for precision diagnosis

$ wuji doctor -v
✅ Environment
✅ Access

── WG1KA06260522012 ──
├─ ✅ EMF disconnect check：sampled 100 valid frames, all 5 fingers normal
│  ├─ ✅ Thumb：100 frames all normal
│  ├─ ✅ Index：100 frames all normal
│  ├─ ✅ Middle：100 frames all normal
│  ├─ ✅ Ring：100 frames all normal
│  └─ ✅ Pinky：100 frames all normal
└─ ⚠ tactile dead-pixel check：sampled 100 valid frames: 0 dead pixels, 0 bad rows, 1 bad cols
   ├─ ✅ Thumb
   ├─ ✅ Index
   ├─ ✅ Middle
   ├─ ✅ Ring
   ├─ ✅ Pinky
   ├─ ✅ Palm
   └─ ⚠ Bad col 0：col 0 exceeds bad-line threshold
   💡 tactile check result is for reference only; use Wuji Studio's full panel test for precision diagnosis
```

`wuji doctor --json` 可以输出 JSON 格式的详细检查结果, 包含 `wuji doctor` 未暴露的大量信息, 便于后续分析

```bash
$ wuji doctor --json

{
  "system": [
    {
      "label": "Environment",
      "layer": "env",
      "status": "pass"
    },
    {
      "label": "Access",
      "layer": "access",
      "status": "pass"
    }
  ],
  "devices": [
    {
      "sn": "WG1KA06260522012",
      "children": [
        {
          "id": "emf_disconnect",
          "label": "EMF disconnect check",
          "layer": "device",
          "status": "pass",
          "summary": "sampled 100 valid frames, all 5 fingers normal",
          "children": [
            {
              "label": "Thumb",
              "layer": "device",
              "status": "pass",
              "summary": "100 frames all normal"
            },
            {
              "label": "Index",
              "layer": "device",
              "status": "pass",
              "summary": "100 frames all normal"
            },
            {
              "label": "Middle",
              "layer": "device",
              "status": "pass",
              "summary": "100 frames all normal"
            },
            {
              "label": "Ring",
              "layer": "device",
              "status": "pass",
              "summary": "100 frames all normal"
            },
            {
              "label": "Pinky",
              "layer": "device",
              "status": "pass",
              "summary": "100 frames all normal"
            }
          ],
          "detail": {
            "abnormal_fingers": [],
            "analyzed_frames": 100,
            "fingers": [
              {
                "abnormal_frames": 0,
                "abnormal_ratio": 0.0,
                "all_low_frames": 0,
                "finger": "thumb",
                "rx_row_frames": 0,
                "status": "pass",
                "total_frames": 100,
                "tx_col_frames": 0,
                "verdict": "Normal"
              },
              {
                "abnormal_frames": 0,
                "abnormal_ratio": 0.0,
                "all_low_frames": 0,
                "finger": "index",
                "rx_row_frames": 0,
                "status": "pass",
                "total_frames": 100,
                "tx_col_frames": 0,
                "verdict": "Normal"
              },
              {
                "abnormal_frames": 0,
                "abnormal_ratio": 0.0,
                "all_low_frames": 0,
                "finger": "middle",
                "rx_row_frames": 0,
                "status": "pass",
                "total_frames": 100,
                "tx_col_frames": 0,
                "verdict": "Normal"
              },
              {
                "abnormal_frames": 0,
                "abnormal_ratio": 0.0,
                "all_low_frames": 0,
                "finger": "ring",
                "rx_row_frames": 0,
                "status": "pass",
                "total_frames": 100,
                "tx_col_frames": 0,
                "verdict": "Normal"
              },
              {
                "abnormal_frames": 0,
                "abnormal_ratio": 0.0,
                "all_low_frames": 0,
                "finger": "pinky",
                "rx_row_frames": 0,
                "status": "pass",
                "total_frames": 100,
                "tx_col_frames": 0,
                "verdict": "Normal"
              }
            ],
            "invalid_frames": 0,
            "sampled_frames": 100
          }
        },
        {
          "id": "tactile_dead_pixel",
          "label": "tactile dead-pixel check",
          "layer": "device",
          "status": "warn",
          "summary": "sampled 100 valid frames: 0 dead pixels, 0 bad rows, 1 bad cols",
          "fix": "tactile check result is for reference only; use Wuji Studio's full panel test for precision diagnosis",
          "children": [
            {
              "label": "Thumb",
              "layer": "device",
              "status": "pass"
            },
            {
              "label": "Index",
              "layer": "device",
              "status": "pass"
            },
...

```

完整输出可参考 [doctor.json](references/doctor.json)
