__author__ = 'Eric'

from .rw_material import RWMaterial
from .rw_material_builder import RWMaterialBuilder, SHADER_DATA, RWTextureSlot
from ..file_io import get_hash
import struct
import bpy
from bpy.props import (StringProperty,
                       BoolProperty,
                       FloatProperty,
                       PointerProperty
                       )

# useful information about map sizes and compression
# https://forums.unrealengine.com/development-discussion/rendering/104172-texture-map-compression?p=892528#post892528

class PbrMaterial(RWMaterial):
    material_name = "PBR Material"
    material_description = "A static model with PBR shading."
    material_has_material_color = True
    material_has_ambient_color = False
    material_use_alpha = False

    albedo_texture: StringProperty(
        name="Albedo/Roughness Map",
        description="This map has albedo (base color) on RGB and roughness on alpha "
                    "(leave empty if no texture desired)",
        default="",
        subtype='FILE_PATH'
    )

    normal_texture: StringProperty(
        name="Normal Map",
        description="The normal map of this material (leave empty if no texture desired)",
        default="",
        subtype='FILE_PATH'
    )

    metallic_texture: StringProperty(
        name="Metallic Map",
        description="The metallic map of this material, grayscale (leave empty if no texture desired)",
        default="",
        subtype='FILE_PATH'
    )

    ao_texture: StringProperty(
        name="AO Map",
        description="The ambient occlusion map of this material, grayscale (leave empty if no texture desired)",
        default="",
        subtype='FILE_PATH'
    )

    @staticmethod
    def set_pointer_property(cls):
        cls.material_data_PBR = PointerProperty(
            type=PbrMaterial
        )

    @staticmethod
    def get_material_data(rw4_material):
        return rw4_material.material_data_PBR

    @staticmethod
    def draw_panel(layout, rw4_material):

        data = rw4_material.material_data_PBR

        layout.prop(data, 'albedo_texture')
        layout.prop(data, 'normal_texture')
        layout.prop(data, 'metallic_texture')
        # layout.prop(data, 'roughness_texture')
        layout.prop(data, 'ao_texture')

    @staticmethod
    def get_material_builder(exporter, rw4_material):
        material_data = rw4_material.material_data_PBR

        material = RWMaterialBuilder()

        RWMaterial.set_general_settings(material, rw4_material, material_data)

        material.shader_id = get_hash("BasicPBR")
        material.unknown_booleans.append(True)
        material.unknown_booleans.append(True)
        material.unknown_booleans.append(True)
        material.unknown_booleans.append(True)

        # -- SHADER CONSTANTS -- #

        # Maybe not necessary: this makes it use vertex color?
        # add showIdentityPS -hasData identityColor 0x218 -exclude 0x200
        # add restoreAlphaPS -hasData 0x218 -exclude 0x200
        material.add_shader_data(0x218, struct.pack('<i', 0x028B7C00))

        # -- TEXTURE SLOTS -- #

        material.texture_slots.append(RWTextureSlot(
            sampler_index=0,
            texture_raster=exporter.add_texture(material_data.albedo_texture)
        ))
        material.texture_slots.append(RWTextureSlot(
            sampler_index=1,
            texture_raster=exporter.add_texture(material_data.normal_texture),
            disable_stage_op=True
        ))
        material.texture_slots.append(RWTextureSlot(
            sampler_index=2,
            texture_raster=exporter.add_texture(material_data.metallic_texture),
            disable_stage_op=True
        ))
        material.texture_slots.append(RWTextureSlot(
            sampler_index=3,
            texture_raster=exporter.add_texture(material_data.ao_texture),
            disable_stage_op=True
        ))

        return material

    @staticmethod
    def parse_material_builder(material, rw4_material):

        if material.shader_id != 0x80000002:
            return False

        for data in material.shader_data:
            print(data)

        # sh_data = material.get_shader_data(0x218)
        # if sh_data is None or sh_data.data is None or len(sh_data.data) != 4:
        #     return False

        material_data = rw4_material.material_data_PBR

        RWMaterial.parse_material_builder(material, rw4_material)

        sh_data = material.get_shader_data(SHADER_DATA['materialParams'])
        if sh_data is not None and len(sh_data.data) == struct.calcsize('<iffff'):
            values = struct.unpack('<iffff', sh_data.data)
            material_data.material_params_1 = values[1]
            material_data.material_params_2 = values[2]
            material_data.material_params_3 = values[3]
            material_data.material_params_4 = values[4]

        return True

    @staticmethod
    def set_texture(obj, material, slot_index, path):
        if slot_index == 0:
            material.rw4.material_data_PBR.albedo_texture = path

            image = bpy.data.images.load(path)

            texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture_node.image = image
            texture_node.location = (-524, 256)

            material.node_tree.links.new(material.node_tree.nodes["Principled BSDF"].inputs["Base Color"],
                                         texture_node.outputs["Color"])

        else:
            material.rw4.material_data_PBR.normal_texture = path

            image = bpy.data.images.load(path)
            image.colorspace_settings.name = 'Non-Color'

            texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture_node.image = image
            texture_node.location = (-524, -37)

            normal_map_node = material.node_tree.nodes.new("ShaderNodeNormalMap")
            normal_map_node.location = (-216, -86)

            material.node_tree.links.new(normal_map_node.inputs["Color"],
                                         texture_node.outputs["Color"])

            material.node_tree.links.new(material.node_tree.nodes["Principled BSDF"].inputs["Normal"],
                                         normal_map_node.outputs["Normal"])
