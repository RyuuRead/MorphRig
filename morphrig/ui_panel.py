# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

import bpy

from .compat import safe_icon

_ROW_CATEGORIES = ("Eyebrows", "Eyes", "Lips", "Vowels", "Emotes", "Extra")


def _is_valid_target_mesh(obj: Optional[bpy.types.Object]) -> bool:
    return (
        obj is not None
        and obj.type == "MESH"
        and obj.data is not None
        and obj.data.shape_keys is not None
    )


def _resolve_target_mesh(
    context: bpy.types.Context,
    auto_assign: bool = True,
) -> Optional[bpy.types.Object]:
    settings = getattr(context.scene, "morphrig", None)
    if settings is None:
        return None
    if _is_valid_target_mesh(settings.target_mesh):
        return settings.target_mesh
    active_obj = getattr(context, "active_object", None)
    if _is_valid_target_mesh(active_obj):
        if auto_assign:
            settings.target_mesh = active_obj
        return active_obj
    if active_obj is not None and active_obj.type == "ARMATURE":
        stored_mesh_name = active_obj.get("morphrig_target_mesh", "")
        if stored_mesh_name:
            candidate = bpy.data.objects.get(stored_mesh_name)
            if _is_valid_target_mesh(candidate):
                if auto_assign:
                    settings.target_mesh = candidate
                return candidate
        from .mmr_bridge import find_face_mesh_for_armature

        mesh_obj = find_face_mesh_for_armature(active_obj, context.scene)
        if _is_valid_target_mesh(mesh_obj):
            if auto_assign:
                settings.target_mesh = mesh_obj
            return mesh_obj
    return None


def _find_board_in_scene(
    context: bpy.types.Context,
    target_mesh: Optional[bpy.types.Object] = None,
) -> Optional[bpy.types.Object]:
    active_obj = getattr(context, "active_object", None)
    if (
        active_obj is not None
        and active_obj.type == "ARMATURE"
        and active_obj.get("morphrig_target_mesh") is not None
        and (
            target_mesh is None
            or active_obj.get("morphrig_target_mesh") == target_mesh.name
        )
    ):
        return active_obj
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    target_name = target_mesh.name if target_mesh is not None else ""
    matched_primary = None
    matched_mouth = None
    fallback_primary = None
    fallback_mouth = None
    for obj in scene.objects:
        if obj.type != "ARMATURE":
            continue
        is_embedded = bool(obj.get("morphrig_embedded", False))
        is_board = (
            is_embedded
            or obj.name.startswith("MorphRig_Board_")
            or ("morphrig_target_mesh" in obj)
        )
        if not is_board:
            continue
        is_mouth = (not is_embedded) and (
            obj.get("morphrig_board_role", "") == "mouth"
            or obj.name.endswith("_Mouth")
        )
        if target_name and obj.get("morphrig_target_mesh", "") == target_name:
            if not is_mouth:
                matched_primary = obj
                break
            if matched_mouth is None:
                matched_mouth = obj
        else:
            if not is_mouth and fallback_primary is None:
                fallback_primary = obj
            elif is_mouth and fallback_mouth is None:
                fallback_mouth = obj
    return matched_primary or matched_mouth or fallback_primary or fallback_mouth


def _set_kuchisync_flag(settings, value: bool) -> None:
    if settings is None:
        return
    import sys

    pkg = sys.modules.get(__package__)
    if pkg is None:
        settings.kuchisync_passthrough = value
        return
    pkg._syncing_kuchisync = True
    try:
        settings.kuchisync_passthrough = value
    finally:
        pkg._syncing_kuchisync = False


def _build_slots_override(settings, target_mesh: bpy.types.Object):
    if settings.last_scanned_mesh != target_mesh.name or len(settings.scanned_items) == 0:
        return None
    from .semantic_mapper import ControlSlot

    return [
        ControlSlot(
            row=item.row_category,
            display_label=item.display_label,
            side=item.side,
            shape_key_name=item.shape_key_name,
            priority=item.priority,
        )
        for item in settings.scanned_items
        if item.enabled
    ]


class MORPHRIG_OT_scan_shape_keys(bpy.types.Operator):
    bl_idname = "morphrig.scan_shape_keys"
    bl_label = "Scan and preview shape keys"
    bl_description = "Scan target mesh shape keys and preview facial board slot mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)
        if settings is None:
            self.report({"WARNING"}, "MorphRig scene settings are unavailable.")
            return {"CANCELLED"}

        target_mesh = _resolve_target_mesh(context, auto_assign=True)
        if target_mesh is None:
            self.report({"WARNING"}, "Select a mesh object with shape keys first.")
            return {"CANCELLED"}

        from .semantic_mapper import scan_mesh_shape_keys

        slots = scan_mesh_shape_keys(
            target_mesh,
            include_emotes=settings.include_emotes_row,
            include_unmapped=settings.include_unmapped_keys,
        )

        settings.scanned_items.clear()
        for slot in slots:
            item = settings.scanned_items.add()
            item.shape_key_name = slot.shape_key_name
            item.display_label = slot.display_label
            item.row_category = slot.row
            item.side = slot.side
            item.enabled = True
            item.priority = slot.priority

        settings.active_scanned_index = 0
        settings.last_scanned_mesh = target_mesh.name
        settings.show_preview_list = True

        self.report(
            {"INFO"},
            f"Scanned {len(slots)} shape key controls for '{target_mesh.name}'.",
        )
        return {"FINISHED"}


class MORPHRIG_OT_generate_board(bpy.types.Operator):
    bl_idname = "morphrig.generate_board"
    bl_label = "Generate facial board"
    bl_description = "Generate a procedural 3D viewport facial board armature for the target mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)
        if settings is None:
            self.report({"WARNING"}, "MorphRig scene settings are unavailable.")
            return {"CANCELLED"}

        target_mesh = _resolve_target_mesh(context, auto_assign=True)
        if target_mesh is None:
            self.report({"WARNING"}, "Select a mesh object with shape keys first.")
            return {"CANCELLED"}

        slots_override = _build_slots_override(settings, target_mesh)
        if slots_override is not None and len(slots_override) == 0:
            self.report(
                {"WARNING"},
                "Enable at least one scanned shape key before generating the board.",
            )
            return {"CANCELLED"}

        from . import rig_builder

        try:
            board = rig_builder.build_facial_board(
                context,
                target_mesh,
                slots_override=slots_override,
                follow_head_bone=settings.follow_head_bone,
                include_emotes=settings.include_emotes_row,
                include_unmapped=settings.include_unmapped_keys,
                board_scale=settings.board_scale,
                track_height=settings.track_height,
                separate_mouth_board=settings.separate_mouth_board,
                merge_into_mmr_rig=settings.merge_into_mmr_rig,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

        _set_kuchisync_flag(settings, False)
        self.report(
            {"INFO"},
            f"Generated facial board '{board.name}' for '{target_mesh.name}'.",
        )
        return {"FINISHED"}


class MORPHRIG_OT_toggle_kuchisync(bpy.types.Operator):
    bl_idname = "morphrig.toggle_kuchisync"
    bl_label = "KuchiSync passthrough (release vowel drivers)"
    bl_description = "Release or re-bind vowel shape key drivers so KuchiSync can write lip-sync keyframes directly"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)
        if settings is None:
            self.report({"WARNING"}, "MorphRig scene settings are unavailable.")
            return {"CANCELLED"}

        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        board = rig_builder.find_board_for_mesh(context, target_mesh)
        if board is None:
            self.report({"WARNING"}, "No MorphRig facial board found in the scene.")
            return {"CANCELLED"}

        new_state = not bool(settings.kuchisync_passthrough)
        updated_count = rig_builder.set_kuchisync_passthrough(
            board,
            target_mesh,
            enabled=new_state,
        )
        _set_kuchisync_flag(settings, new_state)

        status_text = "enabled" if new_state else "disabled"
        self.report(
            {"INFO"},
            f"KuchiSync passthrough {status_text} ({updated_count} vowel drivers updated).",
        )
        return {"FINISHED"}


class MORPHRIG_OT_reset_sliders(bpy.types.Operator):
    bl_idname = "morphrig.reset_sliders"
    bl_label = "Reset all sliders (0.0)"
    bl_description = "Reset all facial board fader sliders back to 0.0"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        board = rig_builder.find_board_for_mesh(context, target_mesh)
        if board is None:
            self.report({"WARNING"}, "No MorphRig facial board found in the scene.")
            return {"CANCELLED"}

        count = rig_builder.reset_all_sliders(board)
        self.report({"INFO"}, f"Reset {count} facial board sliders to 0.0.")
        return {"FINISHED"}


class MORPHRIG_OT_key_all_sliders(bpy.types.Operator):
    bl_idname = "morphrig.key_all_sliders"
    bl_label = "Key all sliders"
    bl_description = "Insert location keyframes for all facial board sliders at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        board = rig_builder.find_board_for_mesh(context, target_mesh)
        if board is None:
            self.report({"WARNING"}, "No MorphRig facial board found in the scene.")
            return {"CANCELLED"}

        count = rig_builder.key_all_sliders(context, board)
        self.report(
            {"INFO"},
            f"Keyframed {count} facial board sliders at frame {context.scene.frame_current}.",
        )
        return {"FINISHED"}


class MORPHRIG_OT_clear_keyframes(bpy.types.Operator):
    bl_idname = "morphrig.clear_keyframes"
    bl_label = "Clear board keyframes"
    bl_description = "Clear all animation keyframes from facial board slider bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        board = rig_builder.find_board_for_mesh(context, target_mesh)
        if board is None:
            self.report({"WARNING"}, "No MorphRig facial board found in the scene.")
            return {"CANCELLED"}

        count = rig_builder.clear_board_keyframes(board)
        self.report(
            {"INFO"},
            f"Cleared {count} slider animation curves from '{board.name}'.",
        )
        return {"FINISHED"}


class MORPHRIG_OT_rebuild_board(bpy.types.Operator):
    bl_idname = "morphrig.rebuild_board"
    bl_label = "Rebuild board"
    bl_description = "Rebuild the facial board armature and drivers using current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)
        if settings is None:
            self.report({"WARNING"}, "MorphRig scene settings are unavailable.")
            return {"CANCELLED"}

        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=True)
        if target_mesh is None:
            existing_board = rig_builder.find_board_for_mesh(context, None)
            if existing_board is not None:
                mesh_name = existing_board.get("morphrig_target_mesh", "")
                candidate = bpy.data.objects.get(mesh_name)
                if _is_valid_target_mesh(candidate):
                    settings.target_mesh = candidate
                    target_mesh = candidate

        if target_mesh is None:
            self.report({"WARNING"}, "Select a mesh object with shape keys to rebuild.")
            return {"CANCELLED"}

        slots_override = _build_slots_override(settings, target_mesh)
        if slots_override is not None and len(slots_override) == 0:
            self.report(
                {"WARNING"},
                "Enable at least one scanned shape key before rebuilding the board.",
            )
            return {"CANCELLED"}

        try:
            board = rig_builder.build_facial_board(
                context,
                target_mesh,
                slots_override=slots_override,
                follow_head_bone=settings.follow_head_bone,
                include_emotes=settings.include_emotes_row,
                include_unmapped=settings.include_unmapped_keys,
                board_scale=settings.board_scale,
                track_height=settings.track_height,
                separate_mouth_board=settings.separate_mouth_board,
                merge_into_mmr_rig=settings.merge_into_mmr_rig,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

        _set_kuchisync_flag(settings, False)
        self.report({"INFO"}, f"Rebuilt facial board '{board.name}'.")
        return {"FINISHED"}


class MORPHRIG_OT_remove_board(bpy.types.Operator):
    bl_idname = "morphrig.remove_board"
    bl_label = "Remove facial board"
    bl_description = "Remove the facial board, procedural widgets, labels, and shape key drivers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)

        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        removed_count = 0
        if target_mesh is not None:
            removed_count = rig_builder.remove_boards_for_mesh(context, target_mesh)

        if removed_count == 0:
            boards = rig_builder.find_boards_for_mesh(context, target_mesh)
            if not boards:
                self.report({"WARNING"}, "No MorphRig facial board found to remove.")
                return {"CANCELLED"}
            for board in boards:
                if rig_builder.remove_facial_board(context, board):
                    removed_count += 1

        _set_kuchisync_flag(settings, False)

        if removed_count == 0:
            self.report({"WARNING"}, "Could not remove MorphRig facial board.")
            return {"CANCELLED"}

        noun = "board" if removed_count == 1 else "boards"
        self.report(
            {"INFO"},
            f"Removed {removed_count} facial {noun} and cleaned drivers.",
        )
        return {"FINISHED"}


class MORPHRIG_OT_toggle_legacy_mmr_emoji(bpy.types.Operator):
    bl_idname = "morphrig.toggle_legacy_mmr_emoji"
    bl_label = "Toggle legacy MMR emoji rig"
    bl_description = "Hide or show the legacy MikuMikuRig emoji rig in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        from . import mmr_bridge

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        mmr_info = mmr_bridge.detect_mmr_rig_info(target_mesh)
        hidden = mmr_bridge.toggle_mmr_emoji_rig(context, mmr_info.armature)
        state_label = "Hidden" if hidden else "Shown"
        self.report({"INFO"}, f"{state_label} legacy MMR emoji rig.")
        return {"FINISHED"}


class MORPHRIG_OT_merge_into_mmr(bpy.types.Operator):
    bl_idname = "morphrig.merge_into_mmr"
    bl_label = "Merge board into MMR rig"
    bl_description = "Embed existing standalone facial board controls into the detected MikuMikuRig armature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = getattr(context.scene, "morphrig", None)

        from . import rig_builder

        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        merged = rig_builder.merge_standalone_boards_into_mmr(context, target_mesh)
        if not merged and target_mesh is not None:
            merged = rig_builder.merge_standalone_boards_into_mmr(context, None)
        if not merged:
            self.report(
                {"WARNING"},
                "No standalone facial board and target MMR rig found to merge.",
            )
            return {"CANCELLED"}

        merged_list = merged if isinstance(merged, (list, tuple)) else [merged]
        primary = merged_list[0] if merged_list else None
        if primary is not None and "morphrig_kuchisync_passthrough" in primary:
            _set_kuchisync_flag(
                settings,
                bool(primary.get("morphrig_kuchisync_passthrough", False)),
            )

        target_name = primary.name if primary is not None else "MMR rig"
        self.report({"INFO"}, f"Merged facial board controls into '{target_name}'.")
        return {"FINISHED"}


class MORPHRIG_PT_main_panel(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_morphrig_main"
    bl_label = "MorphRig facial board"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MorphRig"

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        settings = getattr(context.scene, "morphrig", None)
        if settings is None:
            layout.label(
                text="MorphRig settings are not initialized.",
                icon=safe_icon("ERROR"),
            )
            return

        try:
            self._draw_panel_body(context, layout, settings)
        except Exception as exc:
            err_box = layout.box()
            err_box.label(
                text=f"MorphRig UI error: {exc}",
                icon=safe_icon("ERROR"),
            )

    def _draw_panel_body(self, context: bpy.types.Context, layout, settings):
        target_mesh = _resolve_target_mesh(context, auto_assign=False)
        active_obj = getattr(context, "active_object", None)
        mmr_probe = target_mesh
        if mmr_probe is None and active_obj is not None and active_obj.type == "ARMATURE":
            mmr_probe = active_obj

        from . import mmr_bridge

        mmr_info = mmr_bridge.detect_mmr_rig_info(mmr_probe)

        box1 = layout.box()
        header1 = box1.row()
        header1.label(
            text="MikuMikuRig bridge and target mesh",
            icon=safe_icon("ARMATURE_DATA"),
        )

        status_row = box1.row()
        if mmr_info.armature is not None and mmr_info.is_mmr_rig:
            head_label = mmr_info.head_bone_name or "None"
            status_row.label(
                text=f"MMR linked: {mmr_info.armature.name} (Head: {head_label})",
                icon=safe_icon("CHECKMARK"),
            )
        else:
            status_row.label(
                text="Standalone mode (no MMR armature detected)",
                icon=safe_icon("INFO"),
            )

        if mmr_info.has_legacy_emoji_rig:
            is_hidden = mmr_bridge.is_legacy_emoji_rig_hidden(context, mmr_info.armature)
            legacy_label = (
                "Show legacy MMR emoji rig"
                if is_hidden
                else "Hide legacy MMR emoji rig"
            )
            legacy_icon = safe_icon("HIDE_OFF" if is_hidden else "HIDE_ON")
            box1.operator(
                "morphrig.toggle_legacy_mmr_emoji",
                text=legacy_label,
                icon=legacy_icon,
            )

        box1.prop(settings, "target_mesh", text="Target face mesh")

        if target_mesh is None:
            empty_row = box1.row()
            empty_row.label(
                text="Select a face mesh with shape keys to scan or build.",
                icon=safe_icon("MESH_DATA"),
            )

        scan_row = box1.row()
        scan_row.enabled = target_mesh is not None
        scan_row.operator(
            "morphrig.scan_shape_keys",
            text="Scan and preview shape keys",
            icon=safe_icon("VIEWZOOM"),
        )

        has_preview = (
            target_mesh is not None
            and settings.last_scanned_mesh == target_mesh.name
            and len(settings.scanned_items) > 0
        )
        if has_preview:
            counts = {cat: 0 for cat in _ROW_CATEGORIES}
            enabled_total = 0
            for item in settings.scanned_items:
                if item.enabled:
                    enabled_total += 1
                    if item.row_category in counts:
                        counts[item.row_category] += 1

            summary_grid = box1.grid_flow(
                row_major=True,
                columns=3,
                even_columns=True,
                even_rows=True,
                align=True,
            )
            for cat in _ROW_CATEGORIES:
                summary_grid.label(text=f"{cat}: {counts[cat]}")

            toggle_icon = safe_icon(
                "TRIA_DOWN" if settings.show_preview_list else "TRIA_RIGHT"
            )
            box1.prop(
                settings,
                "show_preview_list",
                text=f"Slot preview ({enabled_total}/{len(settings.scanned_items)})",
                icon=toggle_icon,
                emboss=False,
            )

            if settings.show_preview_list:
                preview_box = box1.box()
                col = preview_box.column(align=True)
                for item in settings.scanned_items:
                    item_row = col.row(align=True)
                    side_suffix = f" ({item.side})" if item.side else ""
                    item_row.prop(item, "enabled", text="")
                    item_row.label(
                        text=f"[{item.row_category}] {item.display_label}{side_suffix}"
                    )
                    item_row.label(text=item.shape_key_name)

        box2 = layout.box()
        header2 = box2.row()
        header2.label(
            text="Facial board builder options",
            icon=safe_icon("PREFERENCES"),
        )
        col2 = box2.column(align=True)
        col2.prop(settings, "merge_into_mmr_rig", text="Merge into MMR rig")
        col2.prop(settings, "follow_head_bone", text="Follow head bone")
        col2.prop(settings, "separate_mouth_board", text="Separate mouth board")
        col2.prop(settings, "include_emotes_row", text="Include emotes row")
        col2.prop(settings, "include_unmapped_keys", text="Include unmapped keys")
        box2.prop(settings, "board_scale", text="Board scale", slider=True)

        gen_row = box2.row()
        gen_row.scale_y = 1.6
        gen_row.enabled = target_mesh is not None
        gen_row.operator(
            "morphrig.generate_board",
            text="Generate facial board",
            icon=safe_icon("OUTLINER_OB_ARMATURE"),
        )

        active_board = _find_board_in_scene(context, target_mesh)
        if active_board is not None:
            box3 = layout.box()
            header3 = box3.row()
            header3.label(
                text="Live board actions and KuchiSync sync",
                icon=safe_icon("POSE_HLT"),
            )

            is_embedded = bool(active_board.get("morphrig_embedded", False))
            if is_embedded:
                box3.row().label(
                    text=f"Embedded in: {active_board.name}",
                    icon=safe_icon("LINKED"),
                )
            elif (
                mmr_info.is_mmr_rig
                and mmr_bridge.is_final_mmr_controller_rig(mmr_info.armature)
            ):
                box3.row().operator(
                    "morphrig.merge_into_mmr",
                    text="Merge board into MMR rig",
                    icon=safe_icon("AUTOMERGE_ON"),
                )

            ks_enabled = bool(settings.kuchisync_passthrough)
            ks_icon = safe_icon("MUTE_IPO_ON" if ks_enabled else "SPEAKER")
            ks_row = box3.row()
            ks_row.operator(
                "morphrig.toggle_kuchisync",
                text="KuchiSync passthrough (release vowel drivers)",
                icon=ks_icon,
                depress=ks_enabled,
            )

            pose_row = box3.row(align=True)
            pose_row.operator(
                "morphrig.reset_sliders",
                text="Reset all sliders (0.0)",
                icon=safe_icon("LOOP_BACK"),
            )
            pose_row.operator(
                "morphrig.key_all_sliders",
                text="Key all sliders",
                icon=safe_icon("KEY_HLT"),
            )

            clear_row = box3.row()
            clear_row.operator(
                "morphrig.clear_keyframes",
                text="Clear board keyframes",
                icon=safe_icon("KEY_DEHLT"),
            )

            maint_row = box3.row(align=True)
            maint_row.operator(
                "morphrig.rebuild_board",
                text="Rebuild board",
                icon=safe_icon("FILE_REFRESH"),
            )
            maint_row.operator(
                "morphrig.remove_board",
                text="Remove facial board",
                icon=safe_icon("TRASH"),
            )


_OPERATOR_CLASSES = (
    MORPHRIG_OT_scan_shape_keys,
    MORPHRIG_OT_generate_board,
    MORPHRIG_OT_toggle_kuchisync,
    MORPHRIG_OT_reset_sliders,
    MORPHRIG_OT_key_all_sliders,
    MORPHRIG_OT_clear_keyframes,
    MORPHRIG_OT_rebuild_board,
    MORPHRIG_OT_remove_board,
    MORPHRIG_OT_toggle_legacy_mmr_emoji,
    MORPHRIG_OT_merge_into_mmr,
)


def refresh_panel_category(context: Optional[bpy.types.Context] = None) -> str:
    from . import mmr_bridge

    target_category = mmr_bridge.resolve_target_panel_category(context)
    is_registered = getattr(MORPHRIG_PT_main_panel, "is_registered", False)
    if is_registered and MORPHRIG_PT_main_panel.bl_category == target_category:
        return target_category

    if is_registered:
        bpy.utils.unregister_class(MORPHRIG_PT_main_panel)

    MORPHRIG_PT_main_panel.bl_category = target_category
    bpy.utils.register_class(MORPHRIG_PT_main_panel)
    return target_category


def register_ui() -> None:
    for cls in _OPERATOR_CLASSES:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    refresh_panel_category()


def unregister_ui() -> None:
    if getattr(MORPHRIG_PT_main_panel, "is_registered", False):
        bpy.utils.unregister_class(MORPHRIG_PT_main_panel)
    for cls in reversed(_OPERATOR_CLASSES):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
