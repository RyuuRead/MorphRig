# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Iterable, Optional

import bpy

HEAD_BONE_PRIORITY = ("c_head.x", "head", "Head", "頭", "头", "DEF-head")
LEGACY_EMOJI_BONES = ("qws_F1", "qws_F2", "qws_F3")
LEGACY_EMOJI_OBJECT_NAMES = ("rew_G1", "rew_G2", "rew_G3")
LEGACY_EMOJI_OBJECT_PREFIX = "mmr_Mouth_Rig"
LEGACY_EMOJI_COLLECTIONS = ("Emoji_Rigtion", "Emoji_Rigvitfy", "Mouth_Rigvitfy")
_MMR_CLASS_PREFIXES = (
    "MMR_",
    "SCENE_PT_MMR_",
    "MMD_Rig_",
    "MMD_Arm_",
    "MMR_key_Options",
)
_MMR_RIG_COLLECTION_NAMES = ("Torso (Redirect)", "_parent")


@dataclass
class MMRContextInfo:
    armature: Optional[bpy.types.Object] = None
    head_bone_name: str = ""
    is_mmr_rig: bool = False
    has_legacy_emoji_rig: bool = False


def _matches_mmr_panel(attr_name: str, cls: type) -> bool:
    module_name = getattr(cls, "__module__", "") or ""
    if "MikuMikuRig" in module_name:
        return True
    cls_name = getattr(cls, "__name__", "") or ""
    bl_idname = getattr(cls, "bl_idname", "") or ""
    for candidate in (attr_name, cls_name, bl_idname):
        if candidate.startswith(_MMR_CLASS_PREFIXES):
            return True
    return False


def resolve_target_panel_category(
    context: Optional[bpy.types.Context] = None,
    dock_in_mmr_tab: Optional[bool] = None,
) -> str:
    if dock_in_mmr_tab is None:
        try:
            from . import get_addon_preferences

            prefs = get_addon_preferences(context)
            dock_in_mmr_tab = bool(getattr(prefs, "dock_in_mmr_tab", True))
        except Exception:
            dock_in_mmr_tab = True

    if not dock_in_mmr_tab:
        return "MorphRig"

    panel_base = getattr(bpy.types, "Panel", None)
    if panel_base is None:
        return "MorphRig"

    fallback_category = ""
    seen_classes: set[type] = set()
    stack = list(panel_base.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen_classes:
            continue
        seen_classes.add(cls)
        stack.extend(cls.__subclasses__())
        if not getattr(cls, "is_registered", False):
            continue
        if getattr(cls, "bl_space_type", "") != "VIEW_3D":
            continue
        if getattr(cls, "bl_region_type", "") != "UI":
            continue
        cls_name = getattr(cls, "__name__", "") or ""
        bl_idname = getattr(cls, "bl_idname", "") or ""
        if not (_matches_mmr_panel(cls_name, cls) or _matches_mmr_panel(bl_idname, cls)):
            continue
        category = (getattr(cls, "bl_category", "") or "").strip()
        if not category or category == "Item":
            continue
        if category == "MMR":
            return category
        if not fallback_category:
            fallback_category = category

    if fallback_category:
        return fallback_category

    for attr_name in dir(bpy.types):
        if not attr_name.startswith(_MMR_CLASS_PREFIXES):
            continue
        try:
            cls = getattr(bpy.types, attr_name, None)
        except Exception:
            continue
        if not isinstance(cls, type) or cls is panel_base:
            continue
        try:
            if not issubclass(cls, panel_base):
                continue
        except TypeError:
            continue
        if getattr(cls, "bl_space_type", "") != "VIEW_3D":
            continue
        if getattr(cls, "bl_region_type", "") != "UI":
            continue
        category = (getattr(cls, "bl_category", "") or "").strip()
        if not category or category == "Item":
            continue
        if category == "MMR":
            return category
        if not fallback_category:
            fallback_category = category

    return fallback_category or "MorphRig"


def _iter_scene_collections(root_collection: Optional[bpy.types.Collection]) -> Iterable[bpy.types.Collection]:
    if root_collection is None:
        return
    stack = [root_collection]
    seen = set()
    while stack:
        coll = stack.pop()
        if coll in seen:
            continue
        seen.add(coll)
        yield coll
        for child in getattr(coll, "children", ()):
            stack.append(child)


def _iter_layer_collections(
    layer_collection: Optional[bpy.types.LayerCollection],
) -> Iterable[bpy.types.LayerCollection]:
    if layer_collection is None:
        return
    stack = [layer_collection]
    while stack:
        lc = stack.pop()
        yield lc
        for child in getattr(lc, "children", ()):
            stack.append(child)


def _find_armature_for_object(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    if obj is None:
        return None
    for mod in getattr(obj, "modifiers", ()) or ():
        if getattr(mod, "type", "") == "ARMATURE":
            mod_obj = getattr(mod, "object", None)
            if mod_obj is not None and getattr(mod_obj, "type", "") == "ARMATURE":
                return mod_obj
    parent = getattr(obj, "parent", None)
    if parent is not None and getattr(parent, "type", "") == "ARMATURE":
        return parent
    if getattr(obj, "type", "") == "ARMATURE":
        return obj
    return None


def _resolve_head_bone_name(arm_obj: bpy.types.Object) -> str:
    arm_data = getattr(arm_obj, "data", None)
    bones = getattr(arm_data, "bones", None)
    if bones is not None:
        for candidate in HEAD_BONE_PRIORITY:
            if candidate in bones:
                return candidate
    pose = getattr(arm_obj, "pose", None)
    pose_bones = getattr(pose, "bones", None)
    if pose_bones is not None:
        for candidate in HEAD_BONE_PRIORITY:
            if candidate in pose_bones:
                return candidate
    return ""


def _check_is_mmr_rig(arm_obj: bpy.types.Object) -> bool:
    mmr_prop = getattr(arm_obj, "mmr", None)
    if mmr_prop is not None and bool(getattr(mmr_prop, "MMR_Arm", False)):
        return True
    if hasattr(arm_obj, "keys") and "mmr" in arm_obj.keys():
        return True
    arm_data = getattr(arm_obj, "data", None)
    bone_colls = getattr(arm_data, "collections", None)
    if bone_colls is not None:
        for coll_name in _MMR_RIG_COLLECTION_NAMES:
            if bone_colls.get(coll_name) is not None:
                return True
    bones = getattr(arm_data, "bones", None)
    if bones is not None and "c_head.x" in bones:
        return True
    return False


def _find_legacy_emoji_objects(scene: Optional[bpy.types.Scene]) -> list[bpy.types.Object]:
    objs = getattr(scene, "objects", None) if scene is not None else getattr(bpy.data, "objects", ())
    matches = []
    for obj in objs or ():
        name = getattr(obj, "name", "")
        if name in LEGACY_EMOJI_OBJECT_NAMES or name.startswith(LEGACY_EMOJI_OBJECT_PREFIX):
            matches.append(obj)
    return matches


def _find_legacy_emoji_collections(scene: Optional[bpy.types.Scene]) -> list[bpy.types.Collection]:
    matches = []
    seen_names = set()
    if scene is not None and getattr(scene, "collection", None) is not None:
        for coll in _iter_scene_collections(scene.collection):
            if coll.name in LEGACY_EMOJI_COLLECTIONS and coll.name not in seen_names:
                seen_names.add(coll.name)
                matches.append(coll)
    for coll_name in LEGACY_EMOJI_COLLECTIONS:
        if coll_name in seen_names:
            continue
        coll = bpy.data.collections.get(coll_name)
        if coll is not None:
            seen_names.add(coll_name)
            matches.append(coll)
    return matches


def _has_legacy_emoji_bones(arm_obj: Optional[bpy.types.Object]) -> bool:
    if arm_obj is None:
        return False
    arm_data = getattr(arm_obj, "data", None)
    bones = getattr(arm_data, "bones", None)
    if bones is not None:
        for bone_name in LEGACY_EMOJI_BONES:
            if bone_name in bones:
                return True
    pose = getattr(arm_obj, "pose", None)
    pose_bones = getattr(pose, "bones", None)
    if pose_bones is not None:
        for bone_name in LEGACY_EMOJI_BONES:
            if bone_name in pose_bones:
                return True
    return False


def detect_mmr_rig_info(mesh_obj: Optional[bpy.types.Object]) -> MMRContextInfo:
    scene = getattr(bpy.context, "scene", None)
    arm_obj = _find_armature_for_object(mesh_obj)
    if arm_obj is None:
        has_emoji = bool(_find_legacy_emoji_objects(scene) or _find_legacy_emoji_collections(scene))
        return MMRContextInfo(
            armature=None,
            head_bone_name="",
            is_mmr_rig=False,
            has_legacy_emoji_rig=has_emoji,
        )

    head_bone_name = _resolve_head_bone_name(arm_obj)
    is_mmr_rig = _check_is_mmr_rig(arm_obj)
    has_emoji = (
        _has_legacy_emoji_bones(arm_obj)
        or bool(_find_legacy_emoji_objects(scene))
        or bool(_find_legacy_emoji_collections(scene))
    )
    return MMRContextInfo(
        armature=arm_obj,
        head_bone_name=head_bone_name,
        is_mmr_rig=is_mmr_rig,
        has_legacy_emoji_rig=has_emoji,
    )


def _resolve_target_armature(
    context: Optional[bpy.types.Context],
    armature_obj: Optional[bpy.types.Object],
) -> Optional[bpy.types.Object]:
    if armature_obj is not None:
        return armature_obj
    if context is None:
        return None
    scene = getattr(context, "scene", None)
    morphrig_props = getattr(scene, "morphrig", None) if scene is not None else None
    target_mesh = getattr(morphrig_props, "target_mesh", None) if morphrig_props is not None else None
    if target_mesh is not None:
        arm = _find_armature_for_object(target_mesh)
        if arm is not None:
            return arm
    active_obj = getattr(context, "active_object", None)
    if active_obj is not None:
        arm = _find_armature_for_object(active_obj)
        if arm is not None:
            return arm
    if scene is not None:
        for obj in getattr(scene, "objects", ()):
            if getattr(obj, "type", "") == "ARMATURE" and _has_legacy_emoji_bones(obj):
                return obj
    return None


def is_legacy_emoji_rig_hidden(
    context: Optional[bpy.types.Context],
    armature_obj: Optional[bpy.types.Object] = None,
) -> bool:
    scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
    arm_obj = _resolve_target_armature(context, armature_obj)

    states: list[bool] = []
    if arm_obj is not None and getattr(arm_obj, "data", None) is not None:
        bones = getattr(arm_obj.data, "bones", None)
        if bones is not None:
            for bone_name in LEGACY_EMOJI_BONES:
                bone = bones.get(bone_name)
                if bone is not None:
                    states.append(bool(getattr(bone, "hide", False)))

    for obj in _find_legacy_emoji_objects(scene):
        hidden = bool(getattr(obj, "hide_viewport", False))
        with suppress(Exception):
            hidden = hidden or bool(obj.hide_get())
        states.append(hidden)

    view_layer = getattr(context, "view_layer", None) if context is not None else None
    layer_lookup = {}
    if view_layer is not None:
        for lc in _iter_layer_collections(getattr(view_layer, "layer_collection", None)):
            if getattr(lc, "collection", None) is not None:
                layer_lookup[lc.collection.name] = lc

    for coll in _find_legacy_emoji_collections(scene):
        coll_hidden = bool(getattr(coll, "hide_viewport", False))
        lc = layer_lookup.get(coll.name)
        if lc is not None:
            coll_hidden = coll_hidden or bool(getattr(lc, "hide_viewport", False))
        states.append(coll_hidden)

    if not states:
        return False
    return all(states)


def toggle_mmr_emoji_rig(
    context: Optional[bpy.types.Context],
    armature_obj: Optional[bpy.types.Object] = None,
    hide: Optional[bool] = None,
) -> bool:
    scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
    arm_obj = _resolve_target_armature(context, armature_obj)

    if hide is None:
        hide = not is_legacy_emoji_rig_hidden(context, arm_obj)
    target_hide = bool(hide)

    if arm_obj is not None and getattr(arm_obj, "data", None) is not None:
        bones = getattr(arm_obj.data, "bones", None)
        if bones is not None:
            for bone_name in LEGACY_EMOJI_BONES:
                bone = bones.get(bone_name)
                if bone is not None:
                    bone.hide = target_hide
        edit_bones = getattr(arm_obj.data, "edit_bones", None)
        if edit_bones is not None and getattr(arm_obj, "mode", "") == "EDIT":
            for bone_name in LEGACY_EMOJI_BONES:
                ebone = edit_bones.get(bone_name)
                if ebone is not None:
                    ebone.hide = target_hide

    for obj in _find_legacy_emoji_objects(scene):
        obj.hide_viewport = target_hide
        with suppress(Exception):
            obj.hide_set(target_hide)

    view_layer = getattr(context, "view_layer", None) if context is not None else None
    layer_lookup = {}
    if view_layer is not None:
        for lc in _iter_layer_collections(getattr(view_layer, "layer_collection", None)):
            if getattr(lc, "collection", None) is not None:
                layer_lookup[lc.collection.name] = lc

    for coll in _find_legacy_emoji_collections(scene):
        coll.hide_viewport = target_hide
        lc = layer_lookup.get(coll.name)
        if lc is not None:
            lc.hide_viewport = target_hide

    return target_hide
