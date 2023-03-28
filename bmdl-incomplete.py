bl_info = {
    "name": "Darkspore BMDL Importer",
    "author": "Emd4600",
    "blender": (2, 80, 0),
    "version": (0, 0, 1),
    "location": "File > Import-Export",
    "description": "Import Darkspore .bmdl model format.",
    "category": "Import-Export"
}

import os
import bpy
import struct
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import unpack_face_list

def readByte(file, endian='<'):
    return struct.unpack(endian + 'b', file.read(1))[0]

def readUByte(file, endian='<'):
    return struct.unpack(endian + 'B', file.read(1))[0]

def readShort(file, endian='<'):
    return struct.unpack(endian + 'h', file.read(2))[0]

def readUShort(file, endian='<'):
    return struct.unpack(endian + 'H', file.read(2))[0]

def readInt(file, endian='<'):
    return struct.unpack(endian + 'i', file.read(4))[0]

def readUInt(file, endian='<'):
    return struct.unpack(endian + 'I', file.read(4))[0]

def readFloat(file, endian='<'):
    return struct.unpack(endian + 'f', file.read(4))[0]

def readBoolean(file, endian='<'):
    return struct.unpack(endian + '?', file.read(1))[0]

def readString(file):
    stringBytes = bytearray()
    byte = readUByte(file)
    while byte != 0:
        stringBytes.append(byte)
        byte = readUByte(file)
    return stringBytes.decode('utf-8')

def expect(valueToExpect, expectedValue, errorString, file):
    if valueToExpect != expectedValue:
        if not useWarnings:
            raise NameError(errorString + "\t" + str(file.tell()))
        else:
            bpy.ops.error.message('INVOKE_DEFAULT', type="Error", message=errorString + "\t" + str(file.tell()))

def loadTexture(mesh, textureType, material, file):
    name = BMDLShaderParamString.getParameter(mesh["shaderStringParams"], textureType)
    if name is not None:
        material.use_nodes = True
        bsdf = material.node_tree.nodes["Principled BSDF"]
        texImage = material.node_tree.nodes.new('ShaderNodeTexImage')
        texImage.image = bpy.data.images.load(os.path.join(os.path.dirname(file.name), name.value.name + '.dds'))
        material.node_tree.links.new(bsdf.inputs['Base Color'], texImage.outputs['Color'])

        offset = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "OffsetUV")
        if offset is not None:
            texImage.location.x = offset.values[0]
            texImage.location.y = offset.values[1]

        scale = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "TileUV")
        if scale is not None:
            texImage.scale.x = scale.values[0]
            texImage.scale.y = scale.values[1]


def importBMDL(file):
    sectionTypes = [BMDLSectionBounds, BMDLSectionHash, BMDLSectionInt, BMDLSectionInt, BMDLSectionName,
                    BMDLSectionObject]
    sectionVariables = ["bounds", "hash", "unkInt1", "unkInt2", "name",
                        "shader",
                        "vertexFormatOffset", "vertexBufferOffset", "meshInfo", "shaderName"]
    meshSectionVariables = ["int1", "int2", "int3", "bounds2", "objectInfo", "shaderFloatParams", "shaderStringParams",
                            "bounds", "unkInt", "firstIndex", "indicesCount"]

    orderedSections = []
    sections = {}
    meshes = []
    objects = []
    vertexFormat = None

    try:
        header = BMDLHeader()
        header.read(file)
        count = min(header.offsetsCount, len(sectionTypes))

        for i in range(0, count):
            file.seek(header.headerSize + header.offsets[i])
            if sectionTypes[i] == BMDLSectionObject:
                sections[sectionVariables[i]] = sectionTypes[i](file, header.headerSize)
            else:
                sections[sectionVariables[i]] = sectionTypes[i](file)
            orderedSections.append(sections[sectionVariables[i]])
        offsetInd = count

        # Read meshes
        for i in range(0, sections["hash"].count):
            mesh = {}
            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionInt(file))
            mesh["int1"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionInt(file))
            mesh["int2"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionInt(file))
            mesh["int3"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            if sections["hash"].count == 1:
                orderedSections.append(BMDLSectionBounds2(file))
                mesh["bounds2"] = orderedSections[-1]
            else:
                orderedSections.append(readInt(file))
                mesh["bounds2"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionObject(file, header.headerSize))
            mesh["objectInfo"] = orderedSections[-1]
            offsetInd += 1

            meshes.append(mesh)
            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionOffset(file))
            sections["vertexFormatOffset"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionOffset(file))
            sections["vertexBufferOffset"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionMesh(file))
            sections["meshInfo"] = orderedSections[-1]
            offsetInd += 1

            file.seek(header.headerSize + header.offsets[offsetInd])
            orderedSections.append(BMDLSectionSimpleName(file))
            sections["shaderName"] = orderedSections[-1]
            offsetInd += 1
        
        # We read the section parameters
        for mesh in meshes:
            shader_properties = []
            num_params = ordered_sections[ordered_sections.index(mesh["int1"]) - 1].count
            print("numParams: " + str(num_params))
            print(header.offsets[offset_ind])
            for i in range(0, num_params):
                file.seek(header.header_size + header.offsets[offset_ind])
                shader_properties.append(BMDLShaderParamFloat(file, header.header_size))
                offset_ind += 1
            # The next offset points to the shader parameters values
            address = header.header_size + mesh["int2"].data_offset
            for shader_param in shader_properties:
                shader_param.read_values(file, address)
                print(shader_param.name + "\t" + str(shader_param.values))
            mesh["shader_float_params"] = shader_properties
            shader_string_params = []
            # is it always 8?
            # Just a guess, unk_int4 has the textures count and unk_int5 the vertex channels count
            for i in range(0, mesh["int2"].unk + mesh["int3"].unk):
                file.seek(header.header_size + header.offsets[offset_ind + 1])
                value = BMDLShaderParamString(file, header.header_size)
                file.seek(header.header_size + header.offsets[offset_ind])
                shader_string_param = BMDLShaderParamString(file, header.header_size, value)
                offset_ind += 2
                shader_string_params.append(shader_string_param)
                print(shader_string_param.name + "\t" + str(shader_string_param.value.name))
            mesh["shader_string_params"] = shader_string_params
            # Here we read the model data
            vertices = []
            triangles = []
            file.seek(header.header_size + sections["vertex_format_offset"].data_offset)
            vertex_format = BMDLVertexFormat(file)
            file.seek(header.header_size + sections["vertex_buffer_offset"].data_offset)
        
            for i in range(0, sections["mesh_info"].vertex_count):
                    vertex = BMDLVertex()
                    vertex.read(file, vertex_format)
                    vertices.append(vertex)
            file.seek(header.header_size + sections["mesh_info"].data_offset)
            
            for i in range(0, sections["mesh_info"].triangle_count):
                    triangles.append((read_ushort(file), read_ushort(file), read_ushort(file)))
            file.seek(header.header_size + sections["shader_name"].data_offset)
            
            for mesh in meshes:
                bounds = []
                for i in range(0, 8):
                    bounds.append(read_float(file))
                mesh["bounds"] = bounds
                mesh["unk_int"] = read_int(file)  # ?
                mesh["first_index"] = read_int(file)
                mesh["indices_count"] = read_int(file)

    finally:
        pass
        # Add data to Blender
        m = bpy.data.meshes.new(sections["shader"].name)
        obj = bpy.data.objects.new(sections["shader"].name, m)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Add vertices
        m.vertices.add(sections["meshInfo"].vertexCount)
        for v, vertex in enumerate(vertices):
            m.vertices[v].co = vertex.pos

        # Add triangles
        m.loop_triangles.add(sections["meshInfo"].triangleCount)
        m.loop_triangles.foreach_set("vertices", unpack_face_list(triangles))

        # Add UVs
        uv_layer = m.uv_layers.new(name="DefaultUV")
        for loop in m.loops:
            uv_layer.data[loop.index].uv = vertices[loop.vertex_index].uv

        # Add vertex colors
        if BMDLVertex.readColor in vertexFormat.fmt:
            color_layer = m.vertex_colors.new(name="Col")
            for poly in m.polygons:
                for loop_index in poly.loop_indices:
                    loop = m.loops[loop_index]
                    color_layer.data[loop_index].color = BMDLVertex.decodeColor(vertices[loop.vertex_index].color)

        # Add materials
        for mesh in meshes:
            material = bpy.data.materials.new(mesh["objectInfo"].name)
            # ... (Material settings remain the same)
            m.materials.append(material)
            mesh["material"] = material

        bpy.ops.object.mode_set(mode='OBJECT')

        # Assign materials to polygons
        for mesh in meshes:
            for t in range(mesh["firstIndex"]//3, mesh["firstIndex"]//3 + mesh["indicesCount"]//3):
                m.polygons[t].material_index = m.materials.find(mesh["material"].name)

        m.update()

        return {'FINISHED'}


class BMDLHeader:
    def __init__(self):
        self.dataSize = 0
        self.headerSize = 0
        self.unk = 4  # usually 4, sometimes 16
        self.offsetsCount = 0
        self.offsets = []  # offsets to what?

    def read(self, file):
        expect(readInt(file), 1, "H001", file)
        expect(readInt(file), 0x6C646D62, "H002", file)  # 'BMDL'
        expect(readInt(file), 2, "H003", file)
        self.headerSize = readInt(file)
        self.dataSize = readInt(file)
        self.value = readInt(file)
        expect(readInt(file), 0, "H004", file)
        self.offsetsCount = readInt(file)
        self.offsets = struct.unpack('<' + str(self.offsetsCount) + "I", file.read(self.offsetsCount * 4))
        expect(self.headerSize + self.dataSize, os.path.getsize(file.name), "H005", file)

class BMDLSectionBounds:
    def __init__(self, file):
        self.dataOffset = readInt(file)
        file.read(12)  # 0
        self.bounds = []
        # 8 floats
        for _ in range(0, 8):
            self.bounds.append(readFloat(file))

    def __str__(self):
        return "BMDLSectionBounds [dataOffset=%d, bounds=%s]" % (self.dataOffset, str(self.bounds))


# An offset, the file hash and an int ?
class BMDLSectionHash:
    def __init__(self, file):
        # Offset to the name
        self.dataOffset = readInt(file)
        self.hash = readUInt(file)
        self.count = readInt(file)

    def __str__(self):
        return "BMDLSectionHash [dataOffset=%d, hash=%x, count=%d]" % (self.dataOffset, self.hash, self.count)


# Just an offset and an int
class BMDLSectionInt:
    def __init__(self, file):
        # Offset to a section with a hash
        # Offset to 8 floats, the same as in BMDLSectionBounds
        self.dataOffset = readInt(file)
        self.unk = readInt(file)

    def __str__(self):
        return "BMDLSectionInt [dataOffset=%d, unk=%d]" % (self.dataOffset, self.unk)


# Offset, padding and the file name
class BMDLSectionName:
    def __init__(self, file):
        self.dataOffset = readInt(file)
        file.read(12)  # 0
        self.name = readString(file)

    def __str__(self):
        return "BMDLSectionName [dataOffset=%d, name=%s]" % (self.dataOffset, self.name)


# Offset, hash, number, number
class BMDLSectionObject:
    def __init__(self, file, baseOffset=0):
        # Offset to string
        self.nameOffset = readInt(file)
        self.hash = readUInt(file)
        self.unk = readInt(file)
        self.count = readInt(file)
        file.seek(baseOffset + self.nameOffset)
        self.name = readString(file)

    def __str__(self):
        return "BMDLSectionObject [nameOffset=%d, hash=%x, unk=%d, count=%d, name=%s]" % \
               (self.nameOffset, self.hash, self.unk, self.count, self.name)


class BMDLSectionBounds2:
    def __init__(self, file):
        self.dataOffset = readInt(file)
        self.bounds = []
        # 8 floats ?
        for _ in range(0, 8):
            self.bounds.append(readFloat(file))

    def __str__(self):
        return "BMDLSectionBounds2 [dataOffset=%d, bounds=%s]" % (self.dataOffset, str(self.bounds))


class BMDLSectionOffset:
    def __init__(self, file):
        # offset to vertex format ?
        # offset to vertex buffer ?
        self.dataOffset = readInt(file)

    def __str__(self):
        return "BMDLSectionOffset [dataOffset=%d]" % self.dataOffset


class BMDLSectionMesh:
    def __init__(self, file):
        self.dataOffset = readInt(file)
        self.vertexCount = readInt(file)
        self.indicesCount = readInt(file)
        self.triangleCount = self.indicesCount // 3
        self.bounds = [readFloat(file) for _ in range(8)]
        self.unk1 = readInt(file)
        self.unk2 = readInt(file)

    def __str__(self):
        return f"BMDLSectionMesh [dataOffset={self.dataOffset}, vertexCount={self.vertexCount}, indicesCount={self.indicesCount}, triangleCount={self.triangleCount}, bounds={self.bounds}, unk1={self.unk1}, unk2={self.unk2}]"

class BMDLSectionSimpleName:
    def __init__(self, file):
        self.dataOffset = readInt(file)
        self.name = readString(file)

    def __str__(self):
        return f"BMDLSectionSimpleName [dataOffset={self.dataOffset}, name={self.name}]"

class BMDLShaderParamFloat:
    def __init__(self, file, baseOffset):
        self.nameOffset = readInt(file)
        self.hash = readInt(file)
        self.dataIndex = readInt(file)
        self.dataLength = readInt(file)
        self.values = []
        file.seek(baseOffset + self.nameOffset)
        self.name = readString(file)

    def readValues(self, file, valuesAddress):
        file.seek(valuesAddress + self.dataIndex * 4)
        self.values = [readFloat(file) for _ in range(self.dataLength)]

    def __str__(self):
        return f"BMDLShaderParamFloat [nameOffset={self.nameOffset}, hash={self.hash:x}, dataIndex={self.dataIndex}, dataLength={self.dataLength}, name={self.name}, values={self.values}]"

    @staticmethod
    def getParameter(parameters, name):
        return next((param for param in parameters if param.name == name), None)

class BMDLShaderParamString:
    def __init__(self, file, baseOffset, value=None):
        self.nameOffset = readInt(file)
        self.hash = readInt(file)
        file.seek(baseOffset + self.nameOffset)
        self.name = readString(file)
        self.value = value

    def __str__(self):
        return f"BMDLShaderParamString [nameOffset={self.nameOffset}, hash={self.hash:x}, name={self.name}, value={self.value}]"

    @staticmethod
    def getParameter(parameters, name):
        return next((param for param in parameters if param.name == name), None)


class BMDLVertex:
    def __init__(self):
        # size: 28 bytes
        self.pos = None
        self.normal = None
        self.tangent = None
        self.uv = None
        self.color = None

    def read(self, file, vertexFormat):
        for fmt in vertexFormat.fmt:
            fmt(self, file)

    def readPosition(self, file):
        self.pos = [readFloat(file), readFloat(file), readFloat(file)]

    def readNormal(self, file):
        self.normal = readInt(file)

    def readTangent(self, file):
        self.tangent = readInt(file)

    def readUV(self, file):
        self.uv = [readFloat(file), 0 - readFloat(file)]

    def readColor(self, file):
        self.color = readInt(file)

    @staticmethod
    def decodeColor(color):
        return [
            ((color & 0xFF0000) >> 16) / 255,
            ((color & 0xFF00) >> 8) / 255,
            (color & 0xFF) / 255
        ]

class BMDLVertexFormat:
    methods = {
        0: BMDLVertex.readPosition,
        1: BMDLVertex.readNormal,
        2: BMDLVertex.readTangent,
        4: BMDLVertex.readUV,
        5: BMDLVertex.readColor
    }

    def __init__(self, file):
        self.fmt = []
        num = readShort(file)
        while num != 0x00FF:
            readShort(file)  # offset
            readShort(file)  # unk
            self.fmt.append(self.methods[readShort(file)])
            num = readShort(file)

    def __str__(self):
        return "BMDLVertexFormat %s" % str(self.fmt)

class ImportBMDL(bpy.types.Operator, ImportHelper):
    bl_idname = "import_my_format.bmdl"
    bl_label = "Import BMDL"
    filename_ext = ".bmdl"
    filter_glob: bpy.props.StringProperty(default="*.bmdl", options={'HIDDEN'})

    def execute(self, context):
        file = open(self.filepath, 'br')
        result = {'CANCELLED'}
        try:
            result = importBMDL(file)
        finally:
            file.close()
        return result


def bmdlImporter_menu_func(self, context):
    self.layout.operator(ImportBMDL.bl_idname, text="Darkspore BMDL Model (.bmdl)")

def register():
    bpy.utils.register_class(ImportBMDL)
    bpy.types.TOPBAR_MT_file_import.append(bmdlImporter_menu_func)

def unregister():
    from sporemodder import rw4Settings
    bpy.utils.unregister_class(ImportBMDL)
    bpy.types.TOPBAR_MT_file_import.remove(bmdlImporter_menu_func)

if __name__ == "__main__":
    register()
