# RVX Projector Blender Add-on
# Copyright 2023 mausimus
# https://mausimus.github.io
# Licensed under GNU General Public License v3.0

bl_info = {
    "name": "RVX Projector",
    "author": "mausimus",
    "version": (0, 1),
    "blender": (3, 3, 0),
    "location": "3DView",
    "description": "Projection-mapper retaining pixel-like look",
    "warning": "",
    "support": "COMMUNITY",
    "wiki_url": "https://github.com/mausimus/rvx-projector",
    "tracker_url": "https://github.com/mausimus/rvx-projector/issues",
    "category": "Scene"
}

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Quaternion, geometry
from bpy.props import FloatProperty

class RVXProjection(bpy.types.Operator):
    """RVX Projector"""
    bl_idname = "rvx.projection"
    bl_label = "RVX: Project"
    bl_options = {'REGISTER', 'UNDO'}

    scale_left: FloatProperty(
        name = "Size Left",
        description = "Quad Scale (left side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    scale_right: FloatProperty(
        name = "Scale Right",
        description = "Quad Scale (right side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    scale_up: FloatProperty(
        name = "Scale Up",
        description = "Quad Scale (upper side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    scale_down: FloatProperty(
        name = "Scale Down",
        description = "Quad Scale (lower side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    underlay_left: FloatProperty(
        name = "Underlay Left",
        description = "Underlay Size (left side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    underlay_right: FloatProperty(
        name = "Underlay Right",
        description = "Underlay Size (right side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    underlay_up: FloatProperty(
        name = "Underlay Up",
        description = "Underlay Size (upper side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    underlay_down: FloatProperty(
        name = "Underlay Down",
        description = "Underlay Size (lower side)",
        default = 1.0,
        min = 0.01,
        max = 50.0
    )

    underlay_threshold: FloatProperty(
        name = "Underlay Threshold",
        description = "Minimum depth step for generating underlay",
        default = 0.0005,
        precision = 6,
        min = 0.0
    )

    max_depth: FloatProperty(
        name = "Maximum Depth",
        description = "Depth cut-off",
        default = 65000.0,
        min = 0.0
    )

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        scene = context.scene
        cam = scene.camera

        if not cam:
            self.report({'ERROR'}, 'No camera in the scene!')
            return {'CANCELLED'}

        if not cam.data.background_images:
            self.report({'ERROR'}, 'No background image attached to camera!')
            return {'CANCELLED'}

        print('RVX: Projection starting')

        # configure rendering of depth output
        scene.render.use_compositing = True
        scene.use_nodes = True
        scene.view_layers[0].use_pass_z = True
        tree = scene.node_tree
        links = tree.links
        for n in tree.nodes:
            tree.nodes.remove(n)
        rl = tree.nodes.new('CompositorNodeRLayers')
        vl = tree.nodes.new('CompositorNodeViewer')
        vl.use_alpha = True
        # link image to viewer
        links.new(rl.outputs[0], vl.inputs[0])
        # link z to viewer alpha
        links.new(rl.outputs['Depth'], vl.inputs[1])

        # render depth map with resolution of camera background image
        print('RVX: Rendering depth map')
        render = context.scene.render        
        img = cam.data.background_images[0].image
        render.resolution_x = img.size[0]
        render.resolution_y = img.size[1]
        bpy.ops.render.render()
        pixels = np.array(bpy.data.images['Viewer Node'].pixels)
        depth = pixels[3::4]

        # calculate vectors from camera towards four edges of the viewport
        cam_rotation = cam.matrix_world.to_quaternion()
        cam_direction = cam_rotation @ Vector((0.0, 0.0, -1.0)).normalized()
        rot_matrix = cam_rotation.to_matrix().to_4x4()
        tr, br, bl, tl = [cam.matrix_world.normalized() @ f for f in cam.data.view_frame(scene=scene)]
        v_bl = bl - cam.location  # bottom-left vector

        # iterate through depth map and create quads for each pixel
        print('RVX: Starting quad generation')
        out_bmesh = bmesh.new()
        offset = 0
        num_quads = 0
        v_width_per_pix = (tr - tl) / render.resolution_x
        v_height_per_pix = (tr - br) / render.resolution_y
        tot_pixels = render.resolution_x * render.resolution_y        
        wm = bpy.context.window_manager
        wm.progress_begin(0, tot_pixels / 1000)
        for y in range(render.resolution_y):
            for x in range(render.resolution_x):
                d = depth[offset]
                if (d < self.max_depth):
                    # vector from camera through center of this pixel
                    v_quad: Vector = v_bl + v_width_per_pix * (x + 0.5) + v_height_per_pix * (y + 0.5)
                    # vector from camera through center of neighbouring pixel
                    v_next: Vector = v_bl + v_width_per_pix * (x + 1.5) + v_height_per_pix * (y + 0.5)

                    # project both vectors onto camera plane at depth distance
                    quad_pos = geometry.intersect_line_plane(
                        cam.location, cam.location + v_quad, cam.location + cam_direction * d, -cam_direction)
                    next_pos = geometry.intersect_line_plane(
                        cam.location, cam.location + v_next, cam.location + cam_direction * d, -cam_direction)

                    # calculate necessary size of half quad at this depth
                    half_size = (next_pos - quad_pos).length / 2

                    # fetch color from background image
                    color = Vector((img.pixels[offset * 4], img.pixels[offset * 4 + 1],
                                img.pixels[offset * 4 + 2], img.pixels[offset * 4 + 3]))

                    # extend behind neighbours
                    scale = [self.scale_left, self.scale_right, self.scale_up, self.scale_down]
                    underlay_h = False
                    if offset > 0 and depth[offset - 1] < d - self.underlay_threshold:
                        scale[0] += self.underlay_left * 2.0
                        underlay_h = True
                    if offset < tot_pixels - 1 and depth[offset + 1] < d - self.underlay_threshold:
                        scale[1] += self.underlay_right * 2.0
                        underlay_h = True

                    # create a quad at intersection of this pixel's vector with camera plane, facing camera
                    if underlay_h:
                        add_quad(out_bmesh, quad_pos, half_size, rot_matrix, color, scale)

                    scale = [self.scale_left, self.scale_right, self.scale_up, self.scale_down]
                    underlay_v = False
                    if offset > render.resolution_x and depth[offset - render.resolution_x] < d - self.underlay_threshold:
                        scale[3] += self.underlay_up * 2.0
                        underlay_v = True
                    if offset < tot_pixels - render.resolution_x - 1 and depth[offset + render.resolution_x] < d - self.underlay_threshold:
                        scale[2] += self.underlay_down * 2.0
                        underlay_v = True

                    # if we need to extend both directions, we'll create a second quad
                    if underlay_v or not underlay_h:
                        add_quad(out_bmesh, quad_pos, half_size, rot_matrix, color, scale)

                    num_quads += 1
                    if num_quads % 1000 == 0:
                        print('RVX: Created', num_quads, 'quads so far')
                offset += 1
                if offset % 1000 == 0:
                    wm.progress_update(offset / 1000)

        # convert final bmesh into mesh
        print('RVX: Merging meshes')
        out_mesh = bpy.data.meshes.new("Projection")
        out_bmesh.to_mesh(out_mesh)

        # configure vertex color attribute
        out_mesh.attributes.active_color_index = 0

        # create object and add to current collection
        obj = bpy.data.objects.new("Projection", out_mesh)
        context.collection.objects.link(obj)

        wm.progress_end()
        print('RVX: Projection finished')
        return {'FINISHED'}

# adds a quad to the output mesh
def add_quad(out_bmesh, pos, size, rot_matrix, color, scale):
    bm = bmesh.new()
    v1 = bm.verts.new((size * scale[1], size * scale[2], 0))
    v2 = bm.verts.new((size * scale[1], -size * scale[3], 0))
    v3 = bm.verts.new((-size * scale[0], -size * scale[3], 0))
    v4 = bm.verts.new((-size * scale[0], size * scale[2], 0))
    bm.faces.new((v4, v3, v2, v1))
    bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)),
                     matrix=rot_matrix, verts=bm.verts)
    bmesh.ops.translate(bm, verts=bm.verts, vec=pos)
    color_layer = bm.loops.layers.color.new("color")
    for face in bm.faces:
        for loop in face.loops:
            loop[color_layer] = color
    mesh = bpy.data.meshes.new("Quad")
    bm.to_mesh(mesh)
    out_bmesh.from_mesh(mesh)
    bpy.data.meshes.remove(mesh)

def menu_func(self, context):
    self.layout.operator(RVXProjection.bl_idname)

def register():
    bpy.utils.register_class(RVXProjection)
    bpy.types.VIEW3D_MT_view.append(menu_func)

def unregister():
    bpy.utils.unregister_class(RVXProjection)
