bl_info = {
    "name": "Darkspore BMDL Importer",
    "author": "Emd4600",
    "version": (0, 0, 1),
    "blender": (2, 80, 0),
    "location": "File > Import-Export",
    "description": "Import Darkspore .bmdl model format.",
    "category": "Import-Export"
}

# Important!
# Don't believe anything I've written. My initial supposition is probably wrong.
# The header has some offsets that point to "sections". Those sections are always made with an offset and X number
# of data -- that data is usually about the offset of the next section --. The value of X depends on the data it's
# representing - I don't know if it follow any arbitrary order or there is some kind of section type identifier
# somewhere; this is the main problem I've had reading these files
#
# Usually, there's only one vertex/triangle buffer, which can be structured in multiple meshes; I think this is able to
# import them.
# Some models have multiple vertex and triangle buffers (and vertex format too). I have no idea how these work

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
        slot = material.texture_slots.add()
        offset = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "OffsetUV")
        if offset is not None:
            slot.offset.x = offset.values[0]
            slot.offset.y = offset.values[1]
        scale = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "TileUV")
        if offset is not None:
            slot.scale.x = scale.values[0]
            slot.scale.y = scale.values[1]

        realPath = "%s\\%s.dds" % (os.path.dirname(file.name), name.value.name)
        img = None
        try:
            img = bpy.data.images.load(realPath)
        except:
            print("Couldn't load texture " + realPath)

        tex = bpy.data.textures.new(name.value.name, type='IMAGE')
        tex.image = img
        slot.texture = tex
        slot.texture_coords = 'UV'


def importBMDL(file):

    # The order in which sections appear. The question is, do they really appear in that order or is this specified by
    # something else?
    sectionTypes = [BMDLSectionBounds, BMDLSectionHash, BMDLSectionInt, BMDLSectionInt, BMDLSectionName,
                    BMDLSectionObject]

    sectionVariables = ["bounds", "hash", "unkInt1", "unkInt2", "name",
                        "shader",
                        # Extra names, put here to show in the log
                        "vertexFormatOffset", "vertexBufferOffset", "meshInfo", "shaderName"]

    meshSectionVariables = ["int1", "int2", "int3", "bounds2", "objectInfo", "shaderFloatParams", "shaderStringParams",
                            "bounds", "unkInt", "firstIndex", "indicesCount"]

    # int1 -> offset to shader float parameters
    # int2 -> offset to shader float parameters values
    # int3 -> offset to shader string parameters

    # a mesh is int1, int2, int3, bounds2 (sometimes without floats), objectInfo

    # For some weird reason, it's like some sections are meant to use the previous section data,
    # even if they are not related
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
            shaderProperties = []
            numParams = orderedSections[orderedSections.index(mesh["int1"])-1].count
            print("numParams: " + str(numParams))
            print(header.offsets[offsetInd])
            for i in range(0, numParams):
                file.seek(header.headerSize + header.offsets[offsetInd])
                shaderProperties.append(BMDLShaderParamFloat(file, header.headerSize))
                offsetInd += 1

            # The next offset points to the shader parameters values
            address = header.headerSize + mesh["int2"].dataOffset
            for shaderParam in shaderProperties:
                shaderParam.readValues(file, address)
                print(shaderParam.name + "\t" + str(shaderParam.values))

            mesh["shaderFloatParams"] = shaderProperties

            shaderStringParams = []
        # is it always 8 ?
        # Just a guess, unkInt4 has the textures count and unkInt5 the vertex channels count
        for i in range(0, mesh["int2"].unk + mesh["int3"].unk):
            file.seek(header.headerSize + header.offsets[offsetInd+1])
            value = BMDLShaderParamString(file, header.headerSize)

            file.seek(header.headerSize + header.offsets[offsetInd])
            shaderStringParam = BMDLShaderParamString(file, header.headerSize, value)

            offsetInd += 2

            shaderStringParams.append(shaderStringParam)
            print(shaderStringParam.name + "\t" + str(shaderStringParam.value.name))

        mesh["shaderStringParams"] = shaderStringParams

        # Here we read the model data

        vertices = []
        triangles = []

        if "vertex_format" in sections:
            file.seek(header.headerSize + sections["vertex_format"].dataOffset)
        else:
            print("Error: vertex format section not found in file")


        file.seek(header.headerSize + sections["vertex_buffer"].dataOffset)
        for i in range(0, sections["mesh_info"].vertexCount):
            vertex = BMDLVertex()
            vertex.read(file, vertexFormat)
            vertices.append(vertex)

        file.seek(header.headerSize + sections["mesh_info"].dataOffset)
        for i in range(0, sections["mesh_info"].triangleCount):
            triangles.append((read_ushort(file), read_ushort(file), read_ushort(file)))

        file.seek(header.headerSize + sections["shader_name"].dataOffset)

        for mesh in meshes:
            bounds = []
            for i in range(0, 8):
                bounds.append(read_float(file))
            mesh["bounds"] = bounds
            mesh["unkInt"] = read_int(file)  # ?
            mesh["firstIndex"] = read_int(file)
            mesh["indicesCount"] = read_int(file)

        # Create mesh and object for each mesh in the file
        for mesh_data in meshes:
            mesh = bpy.data.meshes.new(mesh_data["shaderName"].name)
            obj = bpy.data.objects.new(mesh_data["shaderName"].name, mesh)

            # Link object to the current collection
            bpy.context.collection.objects.link(obj)

            # Create bmesh to construct the mesh
            bm = bmesh.new()

            # Add vertices to the bmesh
            for vertex in vertices:
                bm.verts.new((vertex.x, vertex.y, vertex.z))

            # Add triangles/faces to the bmesh
            for tri in triangles:
                bm.faces.new((bm.verts[tri[0]], bm.verts[tri[1]], bm.verts[tri[2]]))

            # Update and free the bmesh
            bm.normal_update()
            bm.to_mesh(mesh)
            bm.free()

            # Set shading mode to smooth
            for face in mesh.polygons:
                face.use_smooth = True

            # Create materials and assign to the mesh
            material = bpy.data.materials.new(name=mesh_data["shaderName"].name)
            mesh.materials.append(material)

            # Set material properties
            for shader_param in mesh_data["shaderFloatParams"]:
                # Assuming you have updated the set_material_param function for Blender 2.80 API
                set_material_param(material, shader_param.name, shader_param.values)

            for shader_string_param in mesh_data["shaderStringParams"]:
                # Assuming you have updated the set_material_texture function for Blender 2.80 API
                set_material_texture(material, shader_string_param.name, shader_string_param.value.name)

            m = bpy.data.meshes.new(sections["shader"].name)
            obj = bpy.data.objects.new(sections["shader"].name, m)


    finally:
        pass
        # Write log
        # debugFile = open("C:\\Users\\Eric\\Desktop\\" + os.path.basename(file.name) + ".txt", "w")
        # try:
        #     for s in range(len(sectionVariables)):
        #         debugFile.write(sectionVariables[s] + ":\t" + str(sections[sectionVariables[s]]) + "\n")
        #
        #     for mesh in meshes:
        #         for s in meshSectionVariables:
        #             if s in mesh:
        #                 debugFile.write("mesh " + s + ":\t" + str(mesh[s]) + "\n")
        #
        #     if vertexFormat is not None:
        #         debugFile.write("vertexFormat:\t" + str(vertexFormat) + "\n")
        #
        # finally:
        #     debugFile.close()

        # Add data to Blender

        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj

        # Add vertices
        m.vertices.add(sections["meshInfo"].vertexCount)
        for v, vertex in enumerate(vertices):
            m.vertices[v].co = vertex.pos

        # Add triangles
        m.polygons.add(sections["meshInfo"].triangleCount)
        m.polygons.foreach_set("vertices", unpack_face_list(triangles))

        uvTex = m.uv_layers.new(name="DefaultUV")

        for f, face in enumerate(m.polygons):
            uvTex.data[f].uv1 = vertices[face.vertices[0]].uv
            uvTex.data[f].uv2 = vertices[face.vertices[1]].uv
            uvTex.data[f].uv3 = vertices[face.vertices[2]].uv

        if BMDLVertex.readColor in vertexFormat.fmt:
            colorLayer = m.vertex_colors.new(name="Col", alpha=True)

            m.update()

            for t in range(0, sections["meshInfo"].triangleCount):
                for i in range(0, 3):
                    colorLayer.data[t3 + i].color = (BMDLVertex.decodeColor(vertices[triangles[t][i]].color), 1.0)

        m.update(calc_edges=True, calc_loop_triangles=True)


        for mesh in meshes:
            material = bpy.data.materials.new(name=mesh["objectInfo"].name)
            diffuseColor = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "DiffuseTint")
            material.diffuse_color = (diffuseColor.values[0:3], 1.0) if diffuseColor is not None else (1, 1, 1, 1)
            material.use_nodes = True
            bsdf = material.node_tree.nodes["Principled BSDF"]
            bsdf.inputs['Specular'].default_value = 0.5
            specularColor = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "SpecularTint")
            bsdf.inputs['Specular Color'].default_value = specularColor.values if specularColor is not None else (1, 1, 1)
            ambient = BMDLShaderParamFloat.getParameter(mesh["shaderFloatParams"], "AmbiLevel")
            material.ambient = ambient.values[0] if ambient is not None else 1

            loadTexture(mesh, "diffuseMap", material, file)
            loadTexture(mesh, "normalMap", material, file)
            loadTexture(mesh, "envMap", material, file)

            m.materials.append(material)

            mesh["material"] = material

        bpy.ops.object.mode_set(mode='OBJECT')
        for mesh in meshes:
            material_index = m.materials.find(mesh["material"].name)
            for t in range(mesh["firstIndex"]//3, mesh["firstIndex"]//3 + mesh["indicesCount"]//3):
                m.polygons[t].material_index = material_index

        m.update(calc_edges=True, calc_loop_triangles=True)

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
        self.unk = readInt(file)
        expect(readInt(file), 0, "H004", file)
        self.offsetsCount = readInt(file)
        self.offsets = struct.unpack('<' + str(self.offsetsCount) + "I", file.read(self.offsetsCount * 4))

        expect(self.headerSize + self.dataSize, os.path.getsize(file.name), "H005", file)


class BMDLSectionBounds():
    def __init__(self, file):
        self.dataOffset = readInt(file)
        file.read(12)  # 0
        self.bounds = []
        # 8 floats ?
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
        # offset to triangle buffer
        self.dataOffset = readInt(file)
        self.vertexCount = readInt(file)
        self.indicesCount = readInt(file)
        self.triangleCount = self.indicesCount // 3
        self.bounds = []
        # 8 floats ?
        for _ in range(0, 8):
            self.bounds.append(readFloat(file))

        self.unk1 = readInt(file)
        self.unk2 = readInt(file)

    def __str__(self):
        return "BMDLSectionMesh [dataOffset=%d, vertexCount=%s, indicesCount=%d, triangleCount=%d, bounds=%s, " \
               "unk1=%d, unk2=%d]" % (self.dataOffset, self.vertexCount, self.indicesCount, self.triangleCount,
                                      str(self.bounds), self.unk1, self.unk2)


class BMDLSectionSimpleName:
    def __init__(self, file):
        # offset to bounds again
        self.dataOffset = readInt(file)
        # shader name ?
        self.name = readString(file)

    def __str__(self):
        return "BMDLSectionSimpleName [dataOffset=%d, name=%s]" % (self.dataOffset, self.name)


class BMDLShaderParamFloat:
    def __init__(self, file, baseOffset):
        self.nameOffset = readInt(file)
        self.hash = readInt(file)
        self.dataIndex = readInt(file)
        self.dataLength = readInt(file)  # in dwords
        self.values = []

        file.seek(baseOffset + self.nameOffset)
        self.name = readString(file)

    def readValues(self, file, valuesAddress):
        file.seek(valuesAddress + self.dataIndex * 4)
        for i in range(0, self.dataLength):
            self.values.append(readFloat(file))

    def __str__(self):
        return "BMDLShaderParamFloat [nameOffset=%d, hash=%x, dataIndex=%d, dataLength=%d, name=%s, values=%s]" % \
               (self.nameOffset, self.hash, self.dataIndex, self.dataLength, self.name, str(self.values))

    @staticmethod
    def getParameter(parameters, name):
        for param in parameters:
            if param.name == name:
                return param
        return None


class BMDLShaderParamString:
    def __init__(self, file, baseOffset, value=None):
        self.nameOffset = readInt(file)
        self.hash = readInt(file)
        file.seek(baseOffset + self.nameOffset)
        self.name = readString(file)
        self.value = value

    def __str__(self):
        return "BMDLShaderParamString [nameOffset=%d, hash=%x, name=%s, value=\n\t%s]" % \
               (self.nameOffset, self.hash, self.name, str(self.value))

    @staticmethod
    def getParameter(parameters, name):
        print(name)
        for param in parameters:
            print(param.name)
            if param.name == name:
                return param
        return None


class BMDLVertex:
    def __init__(self):
        # size: 28 bytes
        self.pos = None
        # what about this?
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


class ImportBMDL_OT(bpy.types.Operator, ImportHelper):
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
    self.layout.operator(ImportBMDL_OT.bl_idname, text="Darkspore BMDL Model (.bmdl)")

def register():
    bpy.utils.register_class(ImportBMDL)
    bpy.types.TOPBAR_MT_file_import.append(bmdlImporter_menu_func)

def unregister():
    # from sporemodder import rw4Settings
    bpy.utils.unregister_class(ImportBMDL)
    bpy.types.TOPBAR_MT_file_import.remove(bmdlImporter_menu_func)

if __name__ == "__main__":
    register()
