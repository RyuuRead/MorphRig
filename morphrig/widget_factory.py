# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedural bone widget meshes and merged 3D text labels for the facial board.

Widgets are authored in bone-local X-Y space; Board_Root and Mouth Rig bones use
world-aligned local axes while horizontal Face Board sliders align local +Y with +X.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import bpy
from mathutils import Matrix

WIDGET_COLLECTION_PREFIX = "MorphRig_Widgets_"
LABELS_OBJECT_PREFIX = "MorphRig_Labels_"
LABEL_MAT_FACE = "MorphRig_Label_Mat"
LABEL_MAT_MOUTH = "MorphRig_Mouth_Label_Mat"


@dataclass
class TextLabelSpec:
    text: str
    x: float
    y: float
    size: float
    align_x: str = "CENTER"


def ensure_widget_collection(context, char_name: str) -> bpy.types.Collection:
    coll_name = f"{WIDGET_COLLECTION_PREFIX}{char_name}"
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
    scene_root = context.scene.collection
    if scene_root.children.get(coll.name) is None:
        scene_root.children.link(coll)
    coll.hide_viewport = True
    coll.hide_render = True
    return coll


def _create_wire_object(name: str, verts, edges, faces, collection) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.hide_render = True
    if collection is not None:
        collection.objects.link(obj)
    return obj


def _create_box_object(name: str, hx: float, hy: float, hz: float, collection) -> bpy.types.Object:
    verts = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return _create_wire_object(name, verts, [], faces, collection)


def create_board_frame_widget(
    name: str,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    collection,
) -> bpy.types.Object:
    verts = [
        (min_x, min_y, 0.0),
        (max_x, min_y, 0.0),
        (max_x, max_y, 0.0),
        (min_x, max_y, 0.0),
    ]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    return _create_wire_object(name, verts, edges, [], collection)


def create_slider_track_widget(
    name: str,
    track_height: float,
    scale: float,
    collection,
) -> bpy.types.Object:
    hx = 0.0085 * scale
    verts = [
        (-hx, 0.0, 0.0),
        (hx, 0.0, 0.0),
        (hx, track_height, 0.0),
        (-hx, track_height, 0.0),
    ]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    return _create_wire_object(name, verts, edges, [], collection)


def create_slider_cap_widget(name: str, scale: float, collection) -> bpy.types.Object:
    return _create_box_object(name, 0.010 * scale, 0.005 * scale, 0.005 * scale, collection)


def create_mouth_frame_widget(
    name: str,
    box_size: float,
    bar_gap: float,
    collection,
) -> bpy.types.Object:
    bar_y = box_size + bar_gap
    verts = [
        (0.0, 0.0, 0.0),
        (box_size, 0.0, 0.0),
        (box_size, box_size, 0.0),
        (0.0, box_size, 0.0),
        (0.0, bar_y, 0.0),
        (box_size, bar_y, 0.0),
    ]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5)]
    return _create_wire_object(name, verts, edges, [], collection)


def create_mouth_bar_cap_widget(name: str, scale: float, collection) -> bpy.types.Object:
    return _create_box_object(
        name,
        0.030 * scale * 0.5,
        0.014 * scale * 0.5,
        0.008 * scale * 0.5,
        collection,
    )


def create_mouth_joystick_widget(name: str, scale: float, collection) -> bpy.types.Object:
    segments = 24
    verts = []
    edges = []
    for ring_idx, radius in enumerate((0.022 * scale, 0.012 * scale)):
        base = ring_idx * segments
        for index in range(segments):
            angle = (2.0 * math.pi * index) / segments
            verts.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
            edges.append((base + index, base + ((index + 1) % segments)))
    return _create_wire_object(name, verts, edges, [], collection)


def _get_or_create_label_material(
    name: str,
    rgba: tuple[float, float, float, float],
) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.diffuse_color = rgba
    mat.roughness = 1.0
    mat.use_backface_culling = False
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    node_tree = mat.node_tree
    if node_tree is not None:
        nodes = node_tree.nodes
        links = node_tree.links
        nodes.clear()
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = rgba
        emission.inputs["Strength"].default_value = 1.0
        output = nodes.new("ShaderNodeOutputMaterial")
        links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def cleanup_unused_label_materials() -> None:
    for mat_name in (LABEL_MAT_FACE, LABEL_MAT_MOUTH):
        mat = bpy.data.materials.get(mat_name)
        if mat is not None and mat.users == 0:
            bpy.data.materials.remove(mat)


def _create_text_meshes(context, requests) -> list:
    """Convert (name, text, size, align_x) requests to meshes with one depsgraph update.

    Temporary FONT curves, objects and any font datablock loaded by them are removed
    before returning so no orphan data is left behind.
    """
    fonts_before = set(bpy.data.fonts)
    scene_root = context.scene.collection
    temps = []
    for name, text_str, size, align_x in requests:
        curve = bpy.data.curves.new(name=f"{name}_tmp", type="FONT")
        curve.resolution_u = 6
        curve.body = text_str
        curve.size = size
        curve.align_x = align_x
        obj = bpy.data.objects.new(f"{name}_tmp", curve)
        scene_root.objects.link(obj)
        temps.append((name, obj, curve))

    meshes = []
    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        for name, obj, _curve in temps:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(eval_obj)
            mesh.name = name
            meshes.append(mesh)
    finally:
        for _name, obj, curve in temps:
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.curves.remove(curve)
        for font in list(bpy.data.fonts):
            if font not in fonts_before and font.users == 0:
                bpy.data.fonts.remove(font)
    return meshes


def create_board_text_mesh(
    context,
    name: str,
    text_str: str,
    size: float,
    align_x: str = "CENTER",
) -> bpy.types.Mesh:
    return _create_text_meshes(context, [(name, text_str, size, align_x)])[0]


def build_merged_board_labels_object(
    context,
    char_name: str,
    label_specs: Sequence[TextLabelSpec],
    board_armature: bpy.types.Object,
    board_root_bone_name: str = "Board_Root",
    board_root_length: float = 0.1,
    target_collection: Optional[bpy.types.Collection] = None,
    label_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    material_name: str = LABEL_MAT_FACE,
) -> bpy.types.Object:
    """Merge every board label into one non-selectable mesh parented to Board_Root.

    Label (x, y) are board coordinates relative to the Board_Root head, so with the
    parent inverse cancelling the bone length the vertices land at world
    head + (x, 0, y) on the X-Z plane, facing the front camera.
    """
    obj_name = f"{LABELS_OBJECT_PREFIX}{char_name}"
    requests = [
        (f"{obj_name}_{index}", spec.text, spec.size, spec.align_x)
        for index, spec in enumerate(label_specs)
    ]
    text_meshes = _create_text_meshes(context, requests) if requests else []

    verts = []
    faces = []
    for spec, mesh in zip(label_specs, text_meshes):
        offset = len(verts)
        for vert in mesh.vertices:
            co = vert.co
            verts.append((co.x + spec.x, co.y + spec.y, co.z))
        for poly in mesh.polygons:
            faces.append([index + offset for index in poly.vertices])
        bpy.data.meshes.remove(mesh)

    merged = bpy.data.meshes.new(obj_name)
    merged.from_pydata(verts, [], faces)
    merged.update()
    label_mat = _get_or_create_label_material(material_name, label_color)
    merged.materials.append(label_mat)

    labels_obj = bpy.data.objects.new(obj_name, merged)
    collection = target_collection
    if collection is None:
        collection = board_armature.users_collection[0] if board_armature.users_collection else context.scene.collection
    collection.objects.link(labels_obj)

    labels_obj.parent = board_armature
    labels_obj.parent_type = "BONE"
    labels_obj.parent_bone = board_root_bone_name
    labels_obj.matrix_parent_inverse = Matrix.Translation((0.0, -board_root_length, 0.0))
    labels_obj.matrix_basis = Matrix.Identity(4)
    labels_obj.color = label_color
    labels_obj.show_in_front = True
    labels_obj.display_type = "SOLID"
    labels_obj.visible_shadow = False
    labels_obj.hide_select = True
    labels_obj.hide_render = True
    return labels_obj
