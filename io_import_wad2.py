# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Import Quake WAD2 (.wad)",
    "author": "chedap",
    "version": (2023, 11, 14),
    "blender": (4, 0, 0),
    "location": "File > Import-Export",
    "description": "Import textures as materials",
    "category": "Import-Export",
    "doc_url": "https://github.com/c-d-a/io_import_wad2"
}

import bpy, struct, bmesh, math
from bpy_extras.io_utils import ImportHelper
from bpy.props import *
from os.path import isfile

if bpy.app.version < (4,0,0):
    em_socket = 'Emission'
else:
    em_socket = 'Emission Color'

class ImportQuakeWadPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    basepath: StringProperty(name="Base path", default='', subtype='DIR_PATH',
        description="Used for relative naming of imported loose images"\
            "\n\n e.g.:\nC:\\Quake3\\baseq3\\textures\nC:\\Doom3\\base\n")
    emit_suffix: StringProperty(name="Glow texture suffix", default='_luma',
        description="Used for detection of textures to be used for emission")
    def draw(self, context):
        for p in ("basepath", "emit_suffix"):
            self.layout.prop(self, p)

class ImportQuakeWad(bpy.types.Operator, ImportHelper):
    bl_idname = 'import.wad2'
    bl_label = bl_info['name']
    bl_description = bl_info['description']
    bl_options = {'UNDO'}
    filter_glob: StringProperty(default="*.wad;*.bsp", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.PropertyGroup)
    directory: StringProperty()

    option_assets: BoolProperty(name="Mark as assets", default=True,
        description="Mark every new material as asset, tag by wad or folder")
    option_cont: BoolProperty(name="Add containers", default=True,
        description="Create objects to hold new materials")
    option_rel: BoolProperty(name="Relative naming", default=False,
        description="Use relative path for a name when importing loose images"\
            "\n\nYou can change the base path in the addon preferences."\
            "\nWhen on and the path is empty, the path will be relative to"\
            " the current blender file"\
            "\nWhen off, only the image name will be used")
    option_luma: BoolProperty(name="Cut out luma", default=False,
        description="More accurate fullbrights in Eevee & Cycles,"\
                    " but black pixels in Workbench and Asset Browser")
    option_turb: BoolProperty(name="Add water nodes", default=True,
        description="Set up materials for water turbulence")
    option_scroll: BoolProperty(name="Add sky nodes", default=True,
        description="Set up materials for scrolling sky")
    option_seq: BoolProperty(name="Add sequence nodes", default=True,
        description="Set up materials for animated image sequences")
    option_lerp: BoolProperty(name="Interpolated animation", default=False,
        description="Smoothly blend frames in animated image sequences")

    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        pal_float = [rgb/255 for rgb in quake1palette]
        emit_suffix = prefs.emit_suffix if prefs.emit_suffix else '_luma'
        anim_seqs = dict()
        if self.option_turb or self.option_scroll:
            self.make_noodles_pre()
        if self.option_cont:
            if "wads" not in bpy.data.collections:
                wad_coll = bpy.data.collections.new("wads")
                bpy.context.scene.collection.children.link(wad_coll)
            else:
                wad_coll = bpy.data.collections["wads"]

        for file in self.files:
            tempdir = f"{bpy.app.tempdir}/io_import_wad2/{file.name}"
            wadentries = []
            loose_texture = False
            with open (self.directory + file.name, 'rb') as wad:

                # determine format
                sig = wad.read(4)
                if sig == b'WAD2':
                    numentries, diroffset = struct.unpack('<2l', wad.read(2*4))
                    wad.seek(diroffset)
                    fmt = '<3lcch16s'
                    fmtsize = struct.calcsize(fmt)
                    for i in range(numentries):
                        wadentries.append(struct.unpack(fmt,wad.read(fmtsize)))
                elif sig == b'BSP2' or sig == struct.pack('<L',29):
                    header = struct.unpack('<30l',wad.read(30*4))
                    diroffset = header[4]
                    wad.seek(diroffset)
                    numentries = struct.unpack('<l',wad.read(4))[0]
                    for i in range(numentries):
                        offset = struct.unpack('<l',wad.read(4))[0] + diroffset
                        wadentries.append([offset, 0, 0, b'D', 0, 0, b''])
                else:
                    # can't load PCX, indexed TGAs have wrong previews
                    img24 = bpy.data.images.load(self.directory + file.name)
                    if img24.depth == 0:
                        self.report({'WARNING'},f"Skipped {file.name}")
                        bpy.data.images.remove(img24)
                        continue
                    else:
                        loose_texture = True
                        wadentries.append([0, 0, 0, 0, 0, 0, b''])

                # tag / container name
                if loose_texture:
                    cont_name = self.directory.split('\\')[-2]
                else:
                    cont_name = file.name

                # add containers
                if self.option_cont:
                    if cont_name in bpy.data.objects:
                        ob = bpy.data.objects[cont_name]
                    else:
                        curve = bpy.data.curves.new(cont_name, 'FONT')
                        curve.body = cont_name
                        ob = bpy.data.objects.new(cont_name, curve)
                        ob.location.y -= len(wad_coll.objects)
                        wad_coll.objects.link(ob)

                # parse textures
                for wadentry in wadentries:
                    wad.seek(wadentry[0])
                    type = wadentry[3]
                    name = wadentry[6].split(b'\00')[0].decode('ascii')
                    palette = pal_float
                    if loose_texture:
                        if not self.option_rel:
                            name = file.name
                        else:
                            fullpath = self.directory + file.name
                            try:
                                name = bpy.path.relpath(fullpath,
                                                    start=prefs.basepath)
                                name = name.strip('/\\').replace('\\','/')
                            except:
                                name = file.name
                                self.report({'WARNING'},"Could not build"\
                                            f" relative path for {fullpath}")
                        name = name[:name.rfind('.')].replace('#','*')
                    elif name == 'CONCHARS':
                        size = 128, 128
                        pixels = wad.read(128*128)
                    elif name == 'CONBACK':
                        size = 320, 200
                        pixels = wad.read(320*200)
                    elif type == b'D': # miptexture
                        fmt = '<16s6L'
                        fmtsize = struct.calcsize(fmt)
                        miptex = struct.unpack(fmt, wad.read(fmtsize))
                        name = miptex[0].split(b'\00')[0].decode('ascii')
                        size = miptex[1], miptex[2]
                        wad.seek(wadentry[0]+miptex[3])
                        pixels = wad.read(size[0]*size[1])
                    elif type == b'B': # statusbar
                        size = struct.unpack('<2l', wad.read(8))
                        pixels = wad.read(size[0]*size[1])
                    elif type == b'@': # palette
                        size = 16, 16
                        pixels = bytearray(range(256))
                        newpal = struct.unpack('<768B', wad.read(768))
                        palette = [rgb/255 for rgb in newpal]
                    else:
                        self.report({'WARNING'},f"Unrecognized lump {name}")
                        continue

                    # skip duplicates and other unneeded textures
                    name = name.lower()
                    ename = name + emit_suffix
                    if name in bpy.data.materials:
                        if self.option_cont:
                            ob.data.materials.append(bpy.data.materials[name])
                        bpy.data.materials[name].asset_data.tags.new(cont_name)
                        continue
                    if name[0] == '+' and name[1] not in '0a':
                        if not self.option_seq:
                            continue
                        seq_name = '+0' if name[1] in '0123456789' else '+a'
                        seq_name += name[2:]
                        if seq_name in anim_seqs.keys():
                            already_stashed = False
                            for existing in anim_seqs[seq_name]:
                                if existing.name == name:
                                    already_stashed = True
                                    break
                            if already_stashed:
                                if loose_texture:
                                    bpy.data.images.remove(img24)
                                continue
                    if loose_texture and name.endswith(emit_suffix):
                        bpy.data.images.remove(img24)
                        continue

                    pix_rgba = []
                    pix_emit = []
                    if loose_texture: # use loaded image + look for emission
                        img = img24
                        img.name = name
                        img.pack()
                        luma_path = ( self.directory
                                    + file.name[:file.name.rfind('.')]
                                    + emit_suffix
                                    + file.name[file.name.rfind('.'):] )
                        if isfile(luma_path):
                            emit = bpy.data.images.load(luma_path)
                            if emit.depth == 0:
                                bpy.data.images.remove(emit)
                            else:
                                emit.name = ename
                                emit.pack()
                                pix_emit = 'blah'
                    else: # convert from indexed to RGBA + emission
                        for row in reversed(range(size[1])):
                            for clm in range(size[0]):
                                pixel = pixels[row*size[0] + clm]
                                color = palette[pixel*3 : pixel*3+3]
                                alpha = pixel != 255 or name[0] != '{'
                                notfb = pixel < 224 or name.startswith(
                                                            ('sky','*'))
                                if notfb or not alpha:
                                    pix_rgba.extend(color+[alpha])
                                    if pix_emit:
                                        pix_emit.extend([0,0,0,1])
                                else:
                                    if self.option_luma:
                                        pix_rgba.extend([0,0,0,1])
                                    else:
                                        pix_rgba.extend(color+[alpha])
                                    if not pix_emit:
                                        initsize = (size[1]-row-1)*size[0] +clm
                                        pix_emit = [0,0,0,1]*initsize
                                    pix_emit.extend(color+[alpha])
                        img = bpy.data.images.new(name,size[0],size[1])
                        img.pixels = pix_rgba
                        img.pack()
                        if pix_emit:
                            emit = bpy.data.images.new(ename,size[0],size[1])
                            emit.pixels = pix_emit
                            emit.pack()

                    # stash sequence frames
                    if name[0] == '+' and name[1] not in '0a':
                        if seq_name in anim_seqs.keys():
                            anim_seqs[seq_name].append(img)
                            if pix_emit:
                                anim_seqs[seq_name + emit_suffix].append(emit)
                        else:
                            anim_seqs[seq_name] = [img]
                            if pix_emit:
                                anim_seqs[seq_name + emit_suffix] = [emit]
                        continue

                    # create the material
                    mat = bpy.data.materials.new(name)
                    if self.option_cont:
                        ob.data.materials.append(mat)
                    mat.use_nodes = True
                    mat.preview_render_type = 'FLAT'
                    shader = mat.node_tree.nodes['Principled BSDF']
                    if bpy.app.version < (4,0,0):
                        shader.inputs['Specular'].default_value = 0.0
                    else:
                        shader.inputs['Specular IOR Level'].default_value = 0.0
                    img_n = mat.node_tree.nodes.new('ShaderNodeTexImage')
                    img_n.image = img
                    img_n.interpolation = 'Closest'
                    img_n.location = -280, 300
                    links = mat.node_tree.links
                    links.new(img_n.outputs[0], shader.inputs['Base Color'])
                    if pix_emit:
                        emit_n = mat.node_tree.nodes.new('ShaderNodeTexImage')
                        emit_n.image = emit
                        emit_n.interpolation = 'Closest'
                        emit_n.location = -280, -48
                        links.new(emit_n.outputs[0], shader.inputs[em_socket])
                        shader.inputs['Emission Strength'].default_value = 1.0
                    if name[0] == '{':
                        links.new(img_n.outputs[1], shader.inputs['Alpha'])
                        mat.blend_method = 'CLIP'
                        mat.shadow_method = 'CLIP'
                    else:
                        mat.use_backface_culling = True
                    if name.startswith(('sky','*lava','*tele')):
                        links.new(img_n.outputs[0], shader.inputs[em_socket])
                        shader.inputs['Emission Strength'].default_value = 1.0
                        links.remove(shader.inputs['Base Color'].links[0])
                        shader.inputs['Base Color'].default_value = [0,0,0,1]
                    if name[0] in ('*','#'):
                        if self.option_turb:
                            warp_n = mat.node_tree.nodes.new('ShaderNodeGroup')
                            warp_n.node_tree = bpy.data.node_groups['watwarp']
                            warp_n.location = -460, 300
                            links.new(warp_n.outputs[0], img_n.inputs[0])
                        if not name.startswith(('*lava','*tele')):
                            shader.inputs['Alpha'].default_value = 0.75
                            mat.blend_method = 'BLEND'
                            mat.shadow_method = 'HASHED'
                    if name.startswith('sky') and self.option_scroll:
                        mat.shadow_method = 'NONE'
                        output = shader.outputs[0].links[0].to_node
                        tree = mat.node_tree
                        tree.nodes.remove(shader) # leave image for Workbench
                        warp_n = tree.nodes.new('ShaderNodeGroup')
                        warp_n.location = 0, 300
                        warp_n.node_tree = bpy.data.node_groups['skyportal']
                        tree.links.new(warp_n.outputs[0], output.inputs[0])
                        sky = bpy.data.worlds.new(name+"*world")
                        sky.use_nodes = True
                        sky.use_fake_user = True
                        tree = sky.node_tree
                        tree.nodes.clear()
                        warp_n = tree.nodes.new('ShaderNodeGroup')
                        warp_n.node_tree = bpy.data.node_groups['skyscroll']
                        warp_n.location = -160, 0
                        output = tree.nodes.new('ShaderNodeGroup')
                        output.node_tree = bpy.data.node_groups['skydome']
                        output.location = 256, 0
                        for i in range(2):
                            img_n = tree.nodes.new('ShaderNodeTexImage')
                            img_n.image = img
                            img_n.interpolation = 'Closest'
                            tree.links.new(warp_n.outputs[i], img_n.inputs[0])
                            tree.links.new(img_n.outputs[0], output.inputs[i])
                        img_n.location = 0, -256
                        warp_n = output
                        output = tree.nodes.new('ShaderNodeOutputWorld')
                        output.location = 412, 0
                        tree.links.new(warp_n.outputs[0], output.inputs[0])

                    # mark as asset
                    if self.option_assets and bpy.app.version > (3,0,0):
                        mat.asset_mark()
                        mat.asset_data.tags.new(cont_name)
                        img.filepath = f"{tempdir}/{name.replace('*','#')}.png"
                        img.save()
                        if bpy.app.version < (4, 0, 0):
                            bpy.ops.ed.lib_id_load_custom_preview( {"id": mat},
                                        filepath=img.filepath)
                        else:
                            with bpy.context.temp_override(id = mat):
                                bpy.ops.ed.lib_id_load_custom_preview(
                                        filepath=img.filepath)

        if self.option_seq:
            self.make_noodles_post(anim_seqs)

        return {'FINISHED'}


    def compat_new_socket(self, group, in_out, type, name):
        if bpy.app.version < (4,0,0):
            if in_out == 'IN':
                return group.inputs.new(type, name)
            else:
                return group.outputs.new(type, name)
        else:
            return group.interface.new_socket(name, in_out=in_out+'PUT',
                                    socket_type=type.replace('XYZ',''))

    def make_noodles_post(self, anim_seqs):
        # add stashed sequence frames to materials
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        fr_dur = round(fps / 5.0)
        prefs = bpy.context.preferences.addons[__name__].preferences
        emit_suffix = prefs.emit_suffix if prefs.emit_suffix else '_luma'

        for seq_name in anim_seqs.keys():
            if seq_name not in bpy.data.materials:
                continue
            mat = bpy.data.materials[seq_name]
            shader = mat.node_tree.nodes['Principled BSDF']
            links = mat.node_tree.links
            frm0 = shader.inputs['Base Color'].links[0].from_node
            if frm0.type == 'MIX_RGB':
                continue # (fix me?) already set up during previous import
            ename = seq_name + emit_suffix
            fr_mod = (len(anim_seqs[seq_name]) + 1) * fr_dur
            if self.option_lerp:
                drv_ex = f"-(frame % {fr_mod})/{fr_dur} +"
            else:
                drv_ex = f"frame % {fr_mod} < {fr_dur} * "

            mix1 = mat.node_tree.nodes.new('ShaderNodeMixRGB')
            mix1.location = -180, 220
            drv = mix1.inputs[0].driver_add('default_value')
            drv.driver.expression = f"{drv_ex}1"
            frm0.location = -280, 260
            frm0.hide = True
            links.new(frm0.outputs[0], mix1.inputs[2])
            links.new(mix1.outputs[0], shader.inputs['Base Color'])

            has_emit_frames = ( shader.inputs[em_socket].links
                                or ename in anim_seqs.keys() )
            if has_emit_frames:
                emix1 = mat.node_tree.nodes.new('ShaderNodeMixRGB')
                emix1.location = -180, -200
                drv = emix1.inputs[0].driver_add('default_value')
                drv.driver.expression = f"{drv_ex}1"
                if shader.inputs[em_socket].links:
                    efrm0 = shader.inputs[em_socket].links[0].from_node
                    efrm0.location = -280, -400
                    efrm0.hide = True
                    links.new(efrm0.outputs[0], emix1.inputs[2])
                else:
                    efrm0 = None
                    emix1.inputs[2].default_value = (0,0,0,1)
                links.new(emix1.outputs[0], shader.inputs[em_socket])
                shader.inputs['Emission Strength'].default_value = 1.0

            for n, img in enumerate(sorted(anim_seqs[seq_name],
                                    key=lambda frame: frame.name)):
                mix0 = mix1
                mix1 = mat.node_tree.nodes.new('ShaderNodeMixRGB')
                mix1.location = -180 - 160*(n+1), 220
                drv = mix1.inputs[0].driver_add('default_value')
                drv.driver.expression = f"{drv_ex}{n+2}"
                links.new(mix1.outputs[0], mix0.inputs[1])
                frm1 = mat.node_tree.nodes.new('ShaderNodeTexImage')
                frm1.location = -280, 260 + 40*(n+1)
                frm1.hide = True
                frm1.image = img
                frm1.interpolation = 'Closest'
                links.new(frm1.outputs[0], mix1.inputs[2])

                if not has_emit_frames:
                    continue
                emix0 = emix1
                emix1 = mat.node_tree.nodes.new('ShaderNodeMixRGB')
                emix1.location = -180 - 160*(n+1), -200
                drv = emix1.inputs[0].driver_add('default_value')
                drv.driver.expression = f"{drv_ex}{n+2}"
                links.new(emix1.outputs[0], emix0.inputs[1])
                if ename not in anim_seqs.keys():
                    emix1.inputs[2].default_value = (0,0,0,1)
                    continue
                for emit in anim_seqs[ename]:
                    if emit.name == img.name + emit_suffix:
                        efrm1 = mat.node_tree.nodes.new('ShaderNodeTexImage')
                        efrm1.location = -280, -400 - 40*(n+1)
                        efrm1.hide = True
                        efrm1.image = emit
                        efrm1.interpolation = 'Closest'
                        links.new(efrm1.outputs[0], emix1.inputs[2])
                        break
                else:
                    emix1.inputs[2].default_value = (0,0,0,1)

            links.new(frm0.outputs[0], mix1.inputs[1])
            if has_emit_frames:
                if efrm0:
                    links.new(efrm0.outputs[0], emix1.inputs[1])
                else:
                    emix1.inputs[1].default_value = (0,0,0,1)

    def make_noodles_pre(self):
        # create node groups for animated water and sky
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        dx = -180
        waterperiod = 20.0/3.0
        skyperiod = 20.0
        if bpy.context.scene.frame_end == 250: # only change if unmodified
            bpy.context.scene.frame_end = int(skyperiod*fps)
        if self.option_turb and 'watwarp' not in bpy.data.node_groups:
            group = bpy.data.node_groups.new('watwarp', 'ShaderNodeTree')
            coord = group.nodes.new('ShaderNodeTexCoord')
            coord.location = 6*dx, 0
            temp2 = group.nodes.new('NodeGroupOutput')
            self.compat_new_socket(group,'OUT','NodeSocketVectorXYZ','Vector')
            temp1 = group.nodes.new('ShaderNodeVectorMath')
            temp1.operation = 'ADD'
            temp1.inputs[1].default_value = (-0.11,-0.27,0.0)
            temp1.location = dx, 0
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            temp2 = group.nodes.new('ShaderNodeVectorMath')
            temp2.operation = 'ADD'
            temp2.location = 2*dx, 0
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            group.links.new(coord.outputs['UV'], temp2.inputs[0])
            temp1 = group.nodes.new('ShaderNodeVectorMath')
            temp1.operation = 'SCALE'
            temp1.inputs['Scale'].default_value = 0.25
            temp1.location = 3*dx, 64
            group.links.new(temp1.outputs[0], temp2.inputs[1])
            temp2 = group.nodes.new('ShaderNodeCombineXYZ')
            temp2.location = 4*dx, 64
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp1 = group.nodes.new('ShaderNodeTexWave')
            temp1.inputs['Scale'].default_value = math.pi/30
            speed = f"frame*2*pi/({waterperiod}*{fps})"
            drv = temp1.inputs['Phase Offset'].driver_add('default_value')
            drv.driver.expression = speed
            temp1.location = 5*dx, 256
            group.links.new(coord.outputs['UV'], temp1.inputs['Vector'])
            group.links.new(temp1.outputs[0], temp2.inputs[1])
            temp1 = group.nodes.new('ShaderNodeTexWave')
            temp1.bands_direction = 'Y'
            temp1.inputs['Scale'].default_value = math.pi/30
            speed = "2-" + speed
            drv = temp1.inputs['Phase Offset'].driver_add('default_value')
            drv.driver.expression = speed
            temp1.location = 5*dx, -96
            group.links.new(coord.outputs['UV'], temp1.inputs['Vector'])
            group.links.new(temp1.outputs[0], temp2.inputs[0])
        if self.option_scroll and 'skycrop' not in bpy.data.node_groups:
            # crop a 2x1 texture, resulting in one half repeating twice
            group = bpy.data.node_groups.new('skycrop', 'ShaderNodeTree')
            input = group.nodes.new('NodeGroupInput')
            input.location = 7*dx, -104
            self.compat_new_socket(group,'IN','NodeSocketVectorXYZ','Vector')
            self.compat_new_socket(group,'IN','NodeSocketFloat','L/R')
            temp1 = group.nodes.new('NodeGroupOutput')
            self.compat_new_socket(group,'OUT','NodeSocketVectorXYZ','Vector')
            temp2 = group.nodes.new('ShaderNodeMixRGB')
            temp2.location = dx, 0
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp1 = group.nodes.new('ShaderNodeVectorMath')
            temp1.operation = 'ADD'
            temp1.location = 4*dx, -128
            temp1.inputs[1].default_value = (0.5,0.0,0.0)
            group.links.new(input.outputs[0], temp1.inputs[0])
            group.links.new(input.outputs[0], temp2.inputs[1])
            group.links.new(temp1.outputs[0], temp2.inputs[2])
            temp1 = group.nodes.new('ShaderNodeMath')
            temp1.operation = 'ABSOLUTE'
            temp1.location = 2*dx, 32
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            temp2 = group.nodes.new('ShaderNodeMath')
            temp2.operation = 'SUBTRACT'
            temp2.location = 3*dx, 32
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            group.links.new(input.outputs[1], temp2.inputs[1])
            temp1 = group.nodes.new('ShaderNodeMath')
            temp1.operation = 'LESS_THAN'
            temp1.location = 4*dx, 32
            temp1.inputs[1].default_value = 0.5
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            temp2 = group.nodes.new('ShaderNodeMath')
            temp2.operation = 'FRACT'
            temp2.location = 5*dx, 32
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp1 = group.nodes.new('ShaderNodeSeparateXYZ')
            temp1.location = 6*dx, 32
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            group.links.new(input.outputs[0], temp1.inputs[0])
        if self.option_scroll and 'skyscroll' not in bpy.data.node_groups:
            # Q1 sky sphere is supposed to be squashed to a third of its height
            # it may be possible with environment texture node, I didn't bother
            group = bpy.data.node_groups.new('skyscroll', 'ShaderNodeTree')
            coord = group.nodes.new('ShaderNodeTexCoord')
            coord.location = 3*dx, 200
            temp1 = group.nodes.new('NodeGroupOutput')
            self.compat_new_socket(group,'OUT','NodeSocketVectorXYZ','BG')
            self.compat_new_socket(group,'OUT','NodeSocketVectorXYZ','FG')
            temp2 = group.nodes.new('ShaderNodeGroup')
            temp2.node_tree = bpy.data.node_groups['skycrop']
            temp2.inputs[1].default_value = 0.0
            temp2.location = dx, 64
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp1 = group.nodes.new('ShaderNodeMapping')
            temp1.location = 2*dx, 160
            temp1.inputs[3].default_value = [1.0, 2.0, 1.0]
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            group.links.new(coord.outputs['Generated'], temp1.inputs[0])
            speed = f"frame/({skyperiod}*{fps})"
            temp2 = group.nodes.new('ShaderNodeValue')
            drv = temp2.outputs[0].driver_add('default_value')
            drv.driver.expression=speed
            temp2.location = 3*dx, -64
            group.links.new(temp2.outputs[0], temp1.inputs[1])
            temp1 = group.nodes.new('ShaderNodeMapping')
            temp1.location = 2*dx, -128
            temp1.inputs[3].default_value = [1.0, 2.0, 1.0]
            group.links.new(coord.outputs['Generated'], temp1.inputs[0])
            speed = "2*" + speed
            temp2 = group.nodes.new('ShaderNodeValue')
            drv = temp2.outputs[0].driver_add('default_value')
            drv.driver.expression=speed
            temp2.location = 3*dx, -192
            group.links.new(temp2.outputs[0], temp1.inputs[1])
            temp2 = group.nodes.new('ShaderNodeGroup')
            temp2.node_tree = bpy.data.node_groups['skycrop']
            temp2.inputs[1].default_value = 1.0
            temp2.location = dx, -64
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            temp1 = group.nodes['Group Output']
            group.links.new(temp2.outputs[0], temp1.inputs[1])
        if self.option_scroll and 'skydome' not in bpy.data.node_groups:
            group = bpy.data.node_groups.new('skydome', 'ShaderNodeTree')
            input = group.nodes.new('NodeGroupInput')
            input.location = 4*dx, 0
            self.compat_new_socket(group,'IN','NodeSocketColor','BG')
            self.compat_new_socket(group,'IN','NodeSocketColor','FG')
            temp1 = group.nodes.new('ShaderNodeMath')
            temp1.operation = 'GREATER_THAN'
            temp1.location = 3*dx, -64
            temp1.inputs[1].default_value = 0.0
            group.links.new(input.outputs[1], temp1.inputs[0])
            temp2 = group.nodes.new('ShaderNodeMixRGB')
            temp2.location = 3*dx, 128
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            group.links.new(input.outputs[0], temp2.inputs[1])
            group.links.new(input.outputs[1], temp2.inputs[2])
            temp1 = group.nodes.new('ShaderNodeBackground')
            temp1.location = 2*dx, 128
            temp1.inputs[1].default_value = 1.5
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp2 = group.nodes.new('ShaderNodeMixShader')
            temp2.location = dx, 128
            group.links.new(temp1.outputs[0], temp2.inputs[1])
            lpath = group.nodes.new('ShaderNodeLightPath')
            lpath.location = 2*dx, -128
            group.links.new(lpath.outputs['Is Diffuse Ray'], temp2.inputs[0])
            temp1 = group.nodes.new('ShaderNodeBackground')
            temp1.location = 2*dx, 0
            group.links.new(temp1.outputs[0], temp2.inputs[2])
            socket = self.compat_new_socket(group,'IN','NodeSocketColor',
                                                            'Amb Color')
            socket.default_value = [0.5,0.5,0.5,1]
            group.links.new(input.outputs[2], temp1.inputs[0])
            socket = self.compat_new_socket(group,'IN','NodeSocketFloat',
                                                            'Amb Scale')
            socket.default_value = 1.0
            group.links.new(input.outputs[3], temp1.inputs[1])
            temp1 = group.nodes.new('ShaderNodeMixShader')
            temp1.location = 0, 128
            group.links.new(temp2.outputs[0], temp1.inputs[1])
            temp2 = group.nodes.new('ShaderNodeBackground')
            temp2.location = dx, 0
            group.links.new(temp2.outputs[0], temp1.inputs[2])
            socket = self.compat_new_socket(group,'IN','NodeSocketColor',
                                                            'Cam Color')
            socket.default_value = [0.025,0.025,0.025,1]
            group.links.new(input.outputs[4], temp2.inputs[0])
            temp2 = group.nodes.new('ShaderNodeMath')
            temp2.location = dx, -128
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp2.operation = 'MULTIPLY'
            group.links.new(lpath.outputs['Is Camera Ray'], temp2.inputs[0])
            socket = self.compat_new_socket(group,'IN','NodeSocketFloat',
                                                            'Cam Blend')
            socket.default_value, socket.min_value, socket.max_value = 1, 0, 1
            group.links.new(input.outputs[5], temp2.inputs[1])
            temp2 = group.nodes.new('NodeGroupOutput')
            self.compat_new_socket(group,'OUT','NodeSocketShader','Background')
            temp2.location = -dx, 128
            group.links.new(temp1.outputs[0], temp2.inputs[0])
        if self.option_scroll and 'skyportal' not in bpy.data.node_groups:
            group = bpy.data.node_groups.new('skyportal', 'ShaderNodeTree')
            temp1 = group.nodes.new('NodeGroupOutput')
            self.compat_new_socket(group,'OUT','NodeSocketShader','Shader')
            temp2 = group.nodes.new('ShaderNodeMixShader')
            temp2.location = dx, 0
            group.links.new(temp2.outputs[0], temp1.inputs[0])
            temp1 = group.nodes.new('ShaderNodeBsdfTransparent')
            temp1.location = 2*dx, -192
            group.links.new(temp1.outputs[0], temp2.inputs[2])
            temp1 = group.nodes.new('ShaderNodeBsdfGlass')
            temp1.location = 2*dx, 0
            if bpy.app.version < (4,0,0): temp1.distribution = 'SHARP'
            temp1.inputs['IOR'].default_value = 1.0
            group.links.new(temp1.outputs[0], temp2.inputs[1])
            temp1 = group.nodes.new('ShaderNodeMath')
            temp1.operation = 'MAXIMUM'
            temp1.location = 2*dx, 192
            group.links.new(temp1.outputs[0], temp2.inputs[0])
            temp2 = group.nodes.new('ShaderNodeLightPath')
            temp2.location = 3*dx, 64
            group.links.new(temp2.outputs['Is Shadow Ray'],temp1.inputs[0])
            group.links.new(temp2.outputs['Is Reflection Ray'],temp1.inputs[1])


class ResetTexelDensity(bpy.types.Operator):
    bl_idname = 'uv.reset_texel_density_q1'
    bl_label = "Reset Density"
    bl_description = "Rescale UVs of selected faces"
    bl_options = {'REGISTER', 'UNDO'}
    option_scale: FloatProperty(name="Density", default=1.0,
                            description="(texels/unit)")
    option_box: BoolProperty(name="Box Project", default=False,
                            description="Box-project before applying density")

    def calc_area_2d(self, coords):
        x, y = zip(*coords)
        return 0.5*abs(sum( x[i]*(y[i+1]-y[i-1]) for i in range(-1,len(x)-1) ))

    def execute(self, context):
        if self.option_box:
            bpy.ops.uv.cube_project()
        mat_area = dict()
        objs = bpy.context.selected_objects
        if not objs:
            objs = [bpy.context.active_object]
        for obj in objs:
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None: continue

            # measure images
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat.name not in mat_area:
                    mat_area[mat.name] = dict()
                    mat_area[mat.name]['uv'] = mat_area[mat.name]['3d'] = 0
                    width = height = 64
                    if mat.node_tree:
                        for node in mat.node_tree.nodes:
                            if node.type == 'TEX_IMAGE':
                                if node.image.has_data:
                                    width, height = node.image.size
                                    break
                    mat_area[mat.name]['tex'] = width * height

            # measure area
            for face in bm.faces:
                if not face.select: continue
                mat = obj.material_slots[face.material_index].material
                if mat is None: continue
                loop_uvs = [loop[uv_layer].uv for loop in face.loops]
                mat_area[mat.name]['uv'] += self.calc_area_2d(loop_uvs)
                mat_area[mat.name]['3d'] += face.calc_area()

            # apply density
            for face in bm.faces:
                if not face.select: continue
                mat = obj.material_slots[face.material_index].material
                if mat is None: continue
                area = mat_area[mat.name]
                mult = math.sqrt( area['3d'] / (area['tex'] * area['uv']) )
                mult *= self.option_scale
                loop_uvs = [loop[uv_layer].uv for loop in face.loops]
                for uv in loop_uvs:
                    uv *= mult

            bmesh.update_edit_mesh(obj.data)

        return {'FINISHED'}


class ApplyAssetEditMode(bpy.types.Operator):
    bl_idname = 'asset.apply_to_faces'
    bl_label = "Apply to Selection"
    bl_description = "Apply material to selected faces (append slot if needed)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return ( context.object.mode == 'EDIT'
                and context.active_file.id_type == 'MATERIAL' )

    def execute(self, context):
        if bpy.app.version < (4,0,0):
            mat = context.active_file.local_id
        else:
            mat = context.asset.local_id
        if mat is None:
            lib_path = context.preferences.filepaths.asset_libraries.get(
                    context.area.spaces.active.params.asset_library_ref).path
            mat_path = context.active_file.relative_path.split('\\Material/')
            blend_path = f"{lib_path}\\{mat_path[0]}"
            with bpy.data.libraries.load(blend_path) as (src, dest):
                dest.materials = [mat_path[1]]
            mat = bpy.data.materials[mat_path[1]]
            mat.asset_clear()

        objs = bpy.context.selected_objects
        if not objs:
            objs = [bpy.context.active_object]
        for obj in objs:
            mat_idx = obj.data.materials.find(mat.name)
            if mat_idx == -1:
                obj.data.materials.append(mat)
                mat_idx = len(obj.data.materials) - 1
            bm = bmesh.from_edit_mesh(obj.data)
            for face in bm.faces:
                if face.select:
                    face.material_index = mat_idx
            bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportQuakeWad.bl_idname, text="Quake WAD (.wad)")

def menu_func_uv(self, context):
    self.layout.operator(ResetTexelDensity.bl_idname)

def menu_func_asset(self, context):
    self.layout.operator(ApplyAssetEditMode.bl_idname)

def register():
    bpy.utils.register_class(ImportQuakeWadPreferences)
    bpy.utils.register_class(ImportQuakeWad)
    bpy.utils.register_class(ResetTexelDensity)
    bpy.utils.register_class(ApplyAssetEditMode)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.VIEW3D_MT_uv_map.append(menu_func_uv)
    if bpy.app.version > (3,0,0):
        bpy.types.ASSETBROWSER_MT_context_menu.prepend(menu_func_asset)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.VIEW3D_MT_uv_map.remove(menu_func_uv)
    if bpy.app.version > (3,0,0):
        bpy.types.ASSETBROWSER_MT_context_menu.remove(menu_func_asset)
    bpy.utils.unregister_class(ImportQuakeWadPreferences)
    bpy.utils.unregister_class(ImportQuakeWad)
    bpy.utils.unregister_class(ResetTexelDensity)
    bpy.utils.unregister_class(ApplyAssetEditMode)


quake1palette = [0,0,0,          15,15,15,       31,31,31,       47,47,47,
                 63,63,63,       75,75,75,       91,91,91,       107,107,107,
                 123,123,123,    139,139,139,    155,155,155,    171,171,171,
                 187,187,187,    203,203,203,    219,219,219,    235,235,235,
                 15,11,7,        23,15,11,       31,23,11,       39,27,15,
                 47,35,19,       55,43,23,       63,47,23,       75,55,27,
                 83,59,27,       91,67,31,       99,75,31,       107,83,31,
                 115,87,31,      123,95,35,      131,103,35,     143,111,35,
                 11,11,15,       19,19,27,       27,27,39,       39,39,51,
                 47,47,63,       55,55,75,       63,63,87,       71,71,103,
                 79,79,115,      91,91,127,      99,99,139,      107,107,151,
                 115,115,163,    123,123,175,    131,131,187,    139,139,203,
                 0,0,0,          7,7,0,          11,11,0,        19,19,0,
                 27,27,0,        35,35,0,        43,43,7,        47,47,7,
                 55,55,7,        63,63,7,        71,71,7,        75,75,11,
                 83,83,11,       91,91,11,       99,99,11,       107,107,15,
                 7,0,0,          15,0,0,         23,0,0,         31,0,0,
                 39,0,0,         47,0,0,         55,0,0,         63,0,0,
                 71,0,0,         79,0,0,         87,0,0,         95,0,0,
                 103,0,0,        111,0,0,        119,0,0,        127,0,0,
                 19,19,0,        27,27,0,        35,35,0,        47,43,0,
                 55,47,0,        67,55,0,        75,59,7,        87,67,7,
                 95,71,7,        107,75,11,      119,83,15,      131,87,19,
                 139,91,19,      151,95,27,      163,99,31,      175,103,35,
                 35,19,7,        47,23,11,       59,31,15,       75,35,19,
                 87,43,23,       99,47,31,       115,55,35,      127,59,43,
                 143,67,51,      159,79,51,      175,99,47,      191,119,47,
                 207,143,43,     223,171,39,     239,203,31,     255,243,27,
                 11,7,0,         27,19,0,        43,35,15,       55,43,19,
                 71,51,27,       83,55,35,       99,63,43,       111,71,51,
                 127,83,63,      139,95,71,      155,107,83,     167,123,95,
                 183,135,107,    195,147,123,    211,163,139,    227,179,151,
                 171,139,163,    159,127,151,    147,115,135,    139,103,123,
                 127,91,111,     119,83,99,      107,75,87,      95,63,75,
                 87,55,67,       75,47,55,       67,39,47,       55,31,35,
                 43,23,27,       35,19,19,       23,11,11,       15,7,7,
                 187,115,159,    175,107,143,    163,95,131,     151,87,119,
                 139,79,107,     127,75,95,      115,67,83,      107,59,75,
                 95,51,63,       83,43,55,       71,35,43,       59,31,35,
                 47,23,27,       35,19,19,       23,11,11,       15,7,7,
                 219,195,187,    203,179,167,    191,163,155,    175,151,139,
                 163,135,123,    151,123,111,    135,111,95,     123,99,83,
                 107,87,71,      95,75,59,       83,63,51,       67,51,39,
                 55,43,31,       39,31,23,       27,19,15,       15,11,7,
                 111,131,123,    103,123,111,    95,115,103,     87,107,95,
                 79,99,87,       71,91,79,       63,83,71,       55,75,63,
                 47,67,55,       43,59,47,       35,51,39,       31,43,31,
                 23,35,23,       15,27,19,       11,19,11,       7,11,7,
                 255,243,27,     239,223,23,     219,203,19,     203,183,15,
                 187,167,15,     171,151,11,     155,131,7,      139,115,7,
                 123,99,7,       107,83,0,       91,71,0,        75,55,0,
                 59,43,0,        43,31,0,        27,15,0,        11,7,0,
                 0,0,255,        11,11,239,      19,19,223,      27,27,207,
                 35,35,191,      43,43,175,      47,47,159,      47,47,143,
                 47,47,127,      47,47,111,      47,47,95,       43,43,79,
                 35,35,63,       27,27,47,       19,19,31,       11,11,15,
                 43,0,0,         59,0,0,         75,7,0,         95,7,0,
                 111,15,0,       127,23,7,       147,31,7,       163,39,11,
                 183,51,15,      195,75,27,      207,99,43,      219,127,59,
                 227,151,79,     231,171,95,     239,191,119,    247,211,139,
                 167,123,59,     183,155,55,     199,195,55,     231,227,87,
                 127,191,255,    171,231,255,    215,255,255,    103,0,0,
                 139,0, 0,       179,0,0,        215,0,0,        255,0,0,
                 255,243,147,    255,247,199,    255,255,255,    159,91,83]
