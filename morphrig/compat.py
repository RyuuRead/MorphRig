# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

ROW_COLOR_PALETTES = {
    "Board": "THEME09",
    "Tracks": "DEFAULT",
    "Eyebrows": "THEME09",
    "Eyes": "THEME09",
    "Lips": "THEME09",
    "Vowels": "THEME09",
    "Emotes": "THEME03",
    "Extra": "THEME10",
    "R": "THEME01",
    "L": "THEME04",
    "MUTED": "DEFAULT",
}

_VALID_ICONS = None


def set_pose_bone_color(pose_bone, color_palette: str = "DEFAULT"):
    if pose_bone is None:
        return
    if hasattr(pose_bone, "color"):
        pose_bone.color.palette = color_palette
    data_bone = getattr(pose_bone, "bone", None)
    if data_bone is not None and hasattr(data_bone, "color"):
        data_bone.color.palette = color_palette


def assign_bone_to_collection(
    armature_data,
    edit_or_pose_bone,
    collection_name: str,
    color_palette: str = "DEFAULT",
):
    if armature_data is None or edit_or_pose_bone is None:
        return None
    coll = armature_data.collections.get(collection_name)
    if coll is None:
        coll = armature_data.collections.new(collection_name)
        coll.is_visible = True

    if isinstance(edit_or_pose_bone, bpy.types.PoseBone):
        coll.assign(edit_or_pose_bone.bone)
        set_pose_bone_color(edit_or_pose_bone, color_palette)
    else:
        coll.assign(edit_or_pose_bone)
        if hasattr(edit_or_pose_bone, "color"):
            edit_or_pose_bone.color.palette = color_palette
    return coll


def _load_valid_icons() -> frozenset[str]:
    try:
        bl_rna = bpy.types.UILayout.bl_rna
        # Blender stores the UI icon enum on UILayout.bl_rna.functions["label"].parameters["icon"], not properties.
        for fn_name in ("label", "prop"):
            fn = bl_rna.functions.get(fn_name)
            if fn is not None:
                icon_param = fn.parameters.get("icon")
                if icon_param is not None and getattr(icon_param, "enum_items", None):
                    return frozenset(item.identifier for item in icon_param.enum_items)
        icon_prop = bl_rna.properties.get("icon")
        if icon_prop is not None and getattr(icon_prop, "enum_items", None):
            return frozenset(item.identifier for item in icon_prop.enum_items)
    except Exception:
        pass
    return frozenset()


def safe_icon(icon_name: str, fallback: str = "BLANK1") -> str:
    global _VALID_ICONS
    if _VALID_ICONS is None:
        _VALID_ICONS = _load_valid_icons()
    if not _VALID_ICONS:
        return "NONE"
    if icon_name in _VALID_ICONS:
        return icon_name
    if fallback in _VALID_ICONS:
        return fallback
    return "NONE"


def remove_shape_key_driver(target_mesh, shape_key_name: str) -> bool:
    if target_mesh is None or target_mesh.data is None:
        return False
    shape_keys = getattr(target_mesh.data, "shape_keys", None)
    if shape_keys is None or shape_keys.animation_data is None:
        return False
    kb = shape_keys.key_blocks.get(shape_key_name)
    if kb is None:
        return False
    try:
        return bool(kb.driver_remove("value"))
    except RuntimeError:
        return False


def bind_fader_driver(
    target_mesh,
    shape_key_name: str,
    board_armature,
    fader_bone_name: str,
    track_len: float,
    transform_type: str = "LOC_Y",
    direction: float = 1.0,
):
    if target_mesh is None or target_mesh.data is None:
        raise ValueError("target_mesh must be a valid mesh object")
    shape_keys = getattr(target_mesh.data, "shape_keys", None)
    if shape_keys is None:
        raise ValueError("target_mesh has no shape keys")
    kb = shape_keys.key_blocks.get(shape_key_name)
    if kb is None:
        raise KeyError(f"Shape key '{shape_key_name}' not found")

    remove_shape_key_driver(target_mesh, shape_key_name)

    fcurve = kb.driver_add("value")
    driver = fcurve.driver
    # AVERAGE + GENERATOR avoids Auto Run Python Scripts security blocks.
    driver.type = "AVERAGE"

    while driver.variables:
        driver.variables.remove(driver.variables[0])

    var = driver.variables.new()
    var.name = "val"
    var.type = "TRANSFORMS"
    target = var.targets[0]
    target.id = board_armature
    target.bone_target = fader_bone_name
    target.transform_type = transform_type
    target.transform_space = "LOCAL_SPACE"

    while fcurve.modifiers:
        fcurve.modifiers.remove(fcurve.modifiers[0])
    while fcurve.keyframe_points:
        fcurve.keyframe_points.remove(fcurve.keyframe_points[0])

    mod = fcurve.modifiers.new(type="GENERATOR")
    mod.mode = "POLYNOMIAL"
    mod.poly_order = 1
    mod.coefficients[0] = 0.0
    mod.coefficients[1] = float(direction) / max(float(track_len), 1e-6)

    fcurve.update()
    return fcurve


def iter_action_fcurves(action):
    if action is None:
        return
    seen = set()
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        for fc in legacy_fcurves:
            fc_id = fc.as_pointer() if hasattr(fc, "as_pointer") else id(fc)
            if fc_id not in seen:
                seen.add(fc_id)
                yield fc

    layers = getattr(action, "layers", None)
    if layers is not None:
        for layer in layers:
            strips = getattr(layer, "strips", None) or ()
            for strip in strips:
                channelbags = getattr(strip, "channelbags", None) or ()
                for bag in channelbags:
                    bag_fcurves = getattr(bag, "fcurves", None) or ()
                    for fc in bag_fcurves:
                        fc_id = fc.as_pointer() if hasattr(fc, "as_pointer") else id(fc)
                        if fc_id not in seen:
                            seen.add(fc_id)
                            yield fc


def _is_fader_location_fcurve(data_path: str, allowed_paths) -> bool:
    if allowed_paths is not None:
        return data_path in allowed_paths
    return data_path.startswith("pose.bones[") and data_path.endswith("].location")


def clear_fader_keyframes(board_armature, fader_bone_names=None) -> int:
    if board_armature is None:
        return 0
    anim_data = getattr(board_armature, "animation_data", None)
    if anim_data is None or anim_data.action is None:
        return 0

    action = anim_data.action
    allowed_paths = None
    if fader_bone_names is not None:
        allowed_paths = set()
        for name in fader_bone_names:
            allowed_paths.add(f'pose.bones["{name}"].location')
            allowed_paths.add(f"pose.bones['{name}'].location")
        if not allowed_paths:
            return 0

    removed = 0
    containers = []
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        containers.append(legacy_fcurves)

    layers = getattr(action, "layers", None)
    if layers is not None:
        for layer in layers:
            strips = getattr(layer, "strips", None) or ()
            for strip in strips:
                channelbags = getattr(strip, "channelbags", None) or ()
                for bag in channelbags:
                    bag_fcurves = getattr(bag, "fcurves", None)
                    if bag_fcurves is not None:
                        containers.append(bag_fcurves)

    for fcurves_coll in containers:
        to_remove = [
            fc for fc in fcurves_coll if _is_fader_location_fcurve(fc.data_path, allowed_paths)
        ]
        for fc in to_remove:
            fcurves_coll.remove(fc)
            removed += 1

    return removed
