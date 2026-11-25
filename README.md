<div align="center">

# MorphRig

**Procedural 3D Viewport Facial Board UI for Blender and MikuMikuRig**

<img width="780" alt="MorphRig Viewport Preview" src="Viewport%20Preview.png" />

</div>

## Overview

MorphRig generates a 2-lane Face Board and a 2D `a / o-u-i-e` Mouth Joystick Rig directly from a character mesh's shape keys without external `.blend` templates. When MikuMikuRig is present, it embeds facial controls into the generated `RIG-*` armature for unified Pose Mode animation, and falls back to Standalone Mode otherwise.

> Built to dock into the MikuMikuRig N-Panel tab (`MMR`) while keeping standalone boards and non-MMR rigs working out of the box.

---

## Features

| Feature | Description |
| --- | --- |
| **MMR Armature Merge** | Embeds Face and Mouth controls directly into `RIG-*` (parented to the head controller) so body and face animate together in one Pose Mode session, including auto-merge when MMR generates after MorphRig. |
| **Face Board & 2D Mouth Rig** | Pairs a compact 2-lane horizontal Face Board (`1.2x` proportion) on `-X` with a right-side 2D `a / o-u-i-e` Mouth Joystick Rig (`1.15x` proportion) on `+X`, using track-free wireframe frames and shadeless Emission text labels. |
| **Multilingual Mapper** | Maps Japanese (MMD/VRoid), Chinese (Hoyoverse/Bilibili), and English shape keys via NFKC normalization with automatic `R`/`L` pairing. |
| **Security-Safe Drivers** | Uses `AVERAGE` + `GENERATOR` (`POLYNOMIAL`) transform drivers so sliders evaluate without Auto Run Python Scripts warnings. |
| **[KuchiSync](https://github.com/RyuuRead/KuchiSync) Passthrough** | Releases vowel shape key drivers on demand for direct automated lip-sync keyframing, then re-binds cleanly when toggled off. |

---

## Compatibility & Installation

Supported targets: **Blender 4.5 LTS**, **Blender 5.2 LTS**, and **Goo Engine 4.4.3**.

- **Blender 4.5 LTS and 5.2 LTS:** Package the `morphrig/` folder as a `.zip` containing `blender_manifest.toml` at the root, then install via **Edit > Preferences > Get Extensions > Install from Disk**.
- **Goo Engine 4.4.3:** Install the `morphrig/` `.zip` or copy the folder into `scripts/addons/`, then enable **Rigging: MorphRig** under **Edit > Preferences > Add-ons**.

---

## Usage

1. Select a character mesh with shape keys (or its `RIG-*` armature) in the 3D Viewport.
2. Open the `MMR` (or `MorphRig`) sidebar tab and click **Generate facial board**.
3. Switch to Pose Mode on the `RIG-*` armature (or generated board) to drag horizontal sliders or move the 2D `a / o-u-i-e` mouth joystick.
4. Toggle **KuchiSync passthrough (release vowel drivers)** during lip-sync baking, or use **Rebuild board** and **Remove facial board** to clean up without affecting MikuMikuRig bones.

---

## Changelog

### Release 1.1
- **Guard Against Accidental MMR Rigging on Facial Boards:** Fixed a bug where having a MorphRig Facial Board UI selected as the active object allowed MikuMikuRig's **Build a controller** to execute on the board itself (`RIG-MorphRig_Board_*`). Facial boards are now protected from being rigged as MMR character armatures while still pairing cleanly with `RIG-*` rigs.

---

## Credits & License

- Built as a companion add-on for [MikuMikuRig](https://github.com/XiaoFFGel/MikuMikuRig) with [KuchiSync](https://github.com/RyuuRead/KuchiSync) passthrough support.
- Verify headless tests with: `blender --background --factory-startup --python tests/test_morphrig.py`
- Licensed under `GPL-3.0-or-later` ([LICENSE](LICENSE)).
