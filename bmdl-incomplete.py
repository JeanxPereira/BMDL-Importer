bl_info = {
    "name": "BMDL Importer",
    "author": "JeanxPereira, updated by YourName",
    "version": (1, 0),
    "blender": (3, 0, 0),
    "location": "File > Import",
    "description": "Import BMDL models",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export",
}

import bpy
import struct
import os
import math

# Function to read binary data from file
def read_binary(file_path):
    with open(file_path, "rb") as f:
        return f.read()

# Function to unpack binary data into values of a given format
def unpack_from_data(data, format_string, offset):
    return struct.unpack_from(format_string, data, offset)

# BMDL importer class
class BMDLImporter(bpy.types.Operator):
    bl_idname = "import_scene.bmdl"
    bl_label = "Import BMDL"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        # Read binary data from file
        data = read_binary(self.filepath)

        # Unpack header data
        offset = 0
        magic, version, mesh_count = unpack_from_data(data, "<3sII", offset)
        offset += 12

        # Check magic and version number
        if magic != b"BMD" or version != 0x0801:
            raise Exception("Invalid or unsupported BMDL file format")

        # Unpack mesh data
        for i in range(mesh_count):
            mesh_offset, mesh_size = unpack_from_data(data, "<II", offset)
            offset += 8

            # Unpack mesh header data
            vertex_count, index_count, uv_count, bone_count, \
                material_count, unknown = unpack_from_data(data, "<IIIIII", mesh_offset)
            mesh_offset += 24

            # Unpack vertex data
            vertices = []
            for j in range(vertex_count):
                vertex = unpack_from_data(data, "<fffHHHHHHHfBB", mesh_offset)
                vertices.append(vertex)
                mesh_offset += 44

            # Unpack index data
            indices = []
            for j in range(index_count):
                index = unpack_from_data(data, "<H", mesh_offset)[0]
                indices.append(index)
                mesh_offset += 2

            # Create mesh object and set data
            mesh_name = f"mesh_{i}"
            mesh_obj = bpy.data.objects.new(mesh_name, bpy.data.meshes.new(mesh_name))
            context.scene.collection.objects.link(mesh_obj)
            mesh = mesh_obj.data

            mesh.vertices.add(vertex_count)
            for j, vertex in enumerate(vertices):
                mesh.vertices[j].co = (vertex[0], vertex[1], vertex[2])

            mesh.loops.add(index_count)
            mesh.polygons.add(index_count // 3)
            for j in range(index_count // 3):
                poly = mesh.polygons[j]
                poly.loop_start = j * 3
                poly.loop_total = 3
                poly.vertices = [indices[poly.loop_start + k
