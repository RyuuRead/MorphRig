# MorphRig

MorphRig (v0.1.0) is a procedural 3D Viewport facial board add-on for Blender and a companion extension for MikuMikuRig (MMR). It generates an armature-based facial control board directly from a character mesh's shape keys without external `.blend` template dependencies, and falls back to Standalone Mode when MikuMikuRig is not installed or disabled.

## Supported Blender targets

- Goo Engine 4.4.3 (Blender 4.4)
- Blender 4.5 LTS
- Blender 5.2 LTS

## Installation

### Blender 4.5 LTS and 5.2 LTS (extension manifest)

MorphRig includes `morphrig/blender_manifest.toml` for the Blender 4.2+ Extension system.

1. Package the `morphrig/` directory as a `.zip` archive (containing `blender_manifest.toml` and the Python modules at the archive root).
2. In Blender, open **Edit > Preferences > Get Extensions**.
3. Click the drop-down menu in the top-right corner and select **Install from Disk**.
4. Select the `.zip` archive and enable **MorphRig**.

### Goo Engine 4.4.3 (legacy add-on)

MorphRig also includes a `bl_info` dictionary in `morphrig/__init__.py` for legacy add-on loading.

1. Compress the `morphrig/` folder into a `.zip` archive, or copy the `morphrig/` folder into your Goo Engine `scripts/addons/` directory.
2. Open **Edit > Preferences > Add-ons**.
3. Click **Install...** if using a `.zip` archive, then enable **Rigging: MorphRig**.

## MikuMikuRig companion integration

When MikuMikuRig is active, MorphRig integrates with it automatically:

- MorphRig inspects active `MikuMikuRig` panels (`SCENE_PT_MMR_*`, `MMR_*`, `MMD_Rig_*`, `MMD_Arm_*`) and docks its own panel into the `MMR` tab when the `dock_in_mmr_tab` preference is enabled.
- If MikuMikuRig is not installed or disabled, or if `dock_in_mmr_tab` is turned off, MorphRig places its panel in a dedicated `MorphRig` tab.
- When building a board for a rigged character, MorphRig searches the target armature for a head controller in this priority order: `c_head.x -> head -> Head -> 頭 -> 头 -> DEF-head`.
- If MikuMikuRig's static `Emoji_Rig` object or emoji bone collection is present in the scene, MorphRig provides an option to hide it so it does not overlap the procedural board.

## Multilingual shape key mapping

MorphRig normalizes shape key names with Unicode NFKC normalization (converting half-width katakana to full-width and full-width digits to ASCII) and maps them into six board rows:

- `Eyebrows`: brow expressions such as happy, angry, sad, serious, up, down, and furrow.
- `Eyes`: blink, wink, smile, calm, wide, jito, sharp, pain, and lid adjustments.
- `Lips`: mouth shapes and tongue expressions.
- `Vowels`: A, I, U, E, O, and N (`ん`, `n`, `m`) lip-sync shape keys.
- `Emotes`: blush, tears, heart eyes, star eyes, sweat, and similar overlay expressions.
- `Extra`: any remaining non-basis shape keys that do not match the built-in dictionaries.

The mapper supports Japanese (MMD/VRoid), Chinese (Hoyoverse/Bilibili), and English naming conventions. When matching left (`L`) and right (`R`) variants are found (including MMD's convention where `ウィンク` without a suffix pairs with `ウィンク右`), MorphRig groups them into a paired control slot with `R` on the left track and `L` on the right track from the front camera perspective.

## Procedural 3D Viewport board operation

- Select a mesh with shape keys and click **Generate facial board** in the N-Panel.
- MorphRig generates custom 3D mesh widgets (frames, tracks, fader handles, and readable white Emission 3D text labels converted to mesh) procedurally via the Blender Python API.
- The multi-column horizontal slider Face Board is placed to the left of the character (`-X`) when **Separate mouth board** is enabled (or on `+X` when combined).
- With **Separate mouth board** enabled (the default), MorphRig places a 2D Mouth Joystick Rig (`MorphRig_Board_<Character>_Mouth`) to the right of the character (`+X`), pairing the top `a` horizontal bar (`LOC_X`) and the lower 2D `o / u / i / e` joystick box (`LOC_X`, `LOC_Y`).
- In Pose Mode, select a Face Board slider bar and move it along its horizontal track (`G` along local Y / world X), or drag the Mouth Rig `a` bar left-to-right and the 2D `o/u/i/e` ring across X and Z. Non-driving axes, rotation, and scale are locked, and `LIMIT_LOCATION` constraints clamp travel to each track or joystick box.
- Shape key drivers use `AVERAGE` driver type with a linear `FModifierGenerator` (`poly_order = 1`, `coefficients = (0.0, direction / track_len)`), so drivers evaluate without triggering Blender's Auto Run Python Scripts security warning.

## KuchiSync passthrough

To use KuchiSync for automated lip-sync while keeping MorphRig active for facial expressions:

1. Enable **KuchiSync passthrough (release vowel drivers)** in the MorphRig N-Panel.
2. MorphRig releases (detaches) the drivers on the `Vowels` row (`A`, `I`, `U`, `E`, `O`, `N`), allowing KuchiSync to write lip-sync keyframes directly to those shape keys without driver interference.
3. All non-vowel facial sliders (`Eyebrows`, `Eyes`, `Lips`, `Emotes`, `Extra`) remain active.
4. Disable **KuchiSync passthrough (release vowel drivers)** when finished to re-bind the vowel drivers to their board faders.

## Verification

Run the headless test suite from the repository root:

```bash
blender --background --factory-startup --python tests/test_morphrig.py
```

## License

MorphRig is licensed under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`). See [LICENSE](LICENSE) for the full text.
