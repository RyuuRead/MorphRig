# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

bl_info = {
    "name": "MorphRig",
    "author": "RyuuRead",
    "version": (0, 1, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > MikuMikuRig / MorphRig",
    "description": "3D Viewport Facial Board UI generator and MikuMikuRig companion",
    "category": "Rigging",
}

_syncing_kuchisync = False


def get_addon_preferences(context=None):
    ctx = context if context is not None else getattr(bpy, "context", None)
    prefs = getattr(ctx, "preferences", None) if ctx is not None else None
    addons = getattr(prefs, "addons", None) if prefs is not None else None
    if addons is not None:
        addon_id = __package__ or "morphrig"
        entry = addons.get(addon_id)
        if entry is not None and getattr(entry, "preferences", None) is not None:
            return entry.preferences
    return SimpleNamespace(
        dock_in_mmr_tab=True,
        default_board_scale=1.0,
        default_track_height=0.12,
    )


def _on_dock_in_mmr_tab_updated(self, context):
    from . import ui_panel

    ui_panel.refresh_panel_category(context)


def _poll_target_mesh(self, obj):
    return (
        obj is not None
        and obj.type == "MESH"
        and obj.data is not None
        and obj.data.shape_keys is not None
    )


def _on_kuchisync_passthrough_updated(self, context):
    global _syncing_kuchisync
    if _syncing_kuchisync:
        return
    _syncing_kuchisync = True
    try:
        from . import rig_builder

        board = rig_builder.find_board_for_mesh(context, self.target_mesh)
        if board is not None:
            rig_builder.set_kuchisync_passthrough(
                board,
                self.target_mesh,
                self.kuchisync_passthrough,
            )
    finally:
        _syncing_kuchisync = False


class MorphRigPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or "morphrig"

    dock_in_mmr_tab: BoolProperty(
        name="Dock in MikuMikuRig Tab",
        description="Place MorphRig panel inside the MikuMikuRig N-Panel tab when detected",
        default=True,
        update=_on_dock_in_mmr_tab_updated,
    )
    default_board_scale: FloatProperty(
        name="Default Board Scale",
        description="Default scale multiplier for newly generated facial boards",
        default=1.0,
        min=0.2,
        max=5.0,
    )
    default_track_height: FloatProperty(
        name="Default Track Height",
        description="Default vertical travel length of fader sliders",
        default=0.12,
        min=0.04,
        max=0.5,
        unit="LENGTH",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "dock_in_mmr_tab")
        layout.prop(self, "default_board_scale")
        layout.prop(self, "default_track_height")


class MorphRigMappingItem(bpy.types.PropertyGroup):
    shape_key_name: StringProperty(name="Shape Key")
    display_label: StringProperty(name="Display Label")
    row_category: StringProperty(name="Row Category")
    side: StringProperty(name="Side")
    enabled: BoolProperty(name="Enabled", default=True)
    priority: IntProperty(name="Priority", default=100)


class MorphRigSettings(bpy.types.PropertyGroup):
    target_mesh: PointerProperty(
        name="Target Face Mesh",
        description="Mesh object containing facial shape keys",
        type=bpy.types.Object,
        poll=_poll_target_mesh,
    )
    follow_head_bone: BoolProperty(
        name="Follow Head Bone",
        description="Parent the facial board to the detected MikuMikuRig head control bone",
        default=True,
    )
    include_emotes_row: BoolProperty(
        name="Include Emotes Row",
        description="Include eye symbol and expression effect sliders on the board",
        default=True,
    )
    include_unmapped_keys: BoolProperty(
        name="Include Unmapped Keys",
        description="Include unrecognized shape keys in an Extra row",
        default=False,
    )
    separate_mouth_board: BoolProperty(
        name="Separate mouth board",
        description="Generate Lips and Vowels on a separate Mouth facial board armature",
        default=True,
    )
    board_scale: FloatProperty(
        name="Board Scale",
        description="Scale multiplier for the generated facial board",
        default=1.0,
        min=0.2,
        max=3.0,
    )
    track_height: FloatProperty(
        name="Track Height",
        description="Vertical travel length of each fader slider",
        default=0.12,
        min=0.04,
        max=0.5,
        unit="LENGTH",
    )
    kuchisync_passthrough: BoolProperty(
        name="KuchiSync Passthrough",
        description="Release vowel shape key drivers so KuchiSync can write lip-sync keyframes directly",
        default=False,
        update=_on_kuchisync_passthrough_updated,
    )
    show_preview_list: BoolProperty(
        name="Show Preview List",
        description="Expand the scanned shape key mapping list",
        default=False,
    )
    scanned_items: CollectionProperty(
        name="Scanned Shape Keys",
        type=MorphRigMappingItem,
    )
    active_scanned_index: IntProperty(
        name="Active Scanned Index",
        default=0,
    )
    last_scanned_mesh: StringProperty(
        name="Last Scanned Mesh",
        default="",
    )


_CLASSES = (
    MorphRigPreferences,
    MorphRigMappingItem,
    MorphRigSettings,
)


def _deferred_refresh_panel_category():
    from . import ui_panel

    ui_panel.refresh_panel_category()
    return None


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.morphrig = PointerProperty(type=MorphRigSettings)

    from . import ui_panel

    ui_panel.register_ui()
    if hasattr(bpy.app, "timers") and not bpy.app.timers.is_registered(_deferred_refresh_panel_category):
        bpy.app.timers.register(_deferred_refresh_panel_category, first_interval=0.5)


def unregister():
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(_deferred_refresh_panel_category):
        bpy.app.timers.unregister(_deferred_refresh_panel_category)
    from . import ui_panel

    ui_panel.unregister_ui()
    if hasattr(bpy.types.Scene, "morphrig"):
        del bpy.types.Scene.morphrig
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
