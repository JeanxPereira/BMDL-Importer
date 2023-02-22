#Dawngate BMDL Importer 0.1 by chrrox
#Noesis Script made possible by MR. Adults
from inc_noesis import *
import os

def registerNoesisTypes():
	handle = noesis.register("Dawngate", ".bmdl")
	noesis.setHandlerTypeCheck(handle, bmdlmodCheckType)
	noesis.setHandlerLoadModel(handle, bmdlmodLoadModel)
	#noesis.logPopup()

	return 1


def bmdlmodCheckType(data):
	td = NoeBitStream(data)
	return 1

class bmdlFile:
	def __init__(self, bs):
		self.bs       = bs
		self.texList  = []
		self.matList  = [] 
		self.boneList = []
		self.boneMap  = []
		self.modelType = 0
		self.matCount    = 0
		self.fvfCount    = 0
		self.bufferCount = 0

	def loadHeader(self, bs):
		modelVersion 	= bs.readUInt()
		modelMagic 	= bs.readUInt()
		modelSubVersion = bs.readUInt()
		self.dataStart 	= bs.readUInt()
		dataSize 	= bs.readUInt()
		self.modelType 	= bs.readUInt()
		modelNull 	= bs.readUInt()
		headerCount 	= bs.readUInt()

	def loadAll(self, bs):
		self.loadHeader(bs)
		if self.modelType == 4:
			self.loadStart04(bs)
			self.baseOffset  = 0x34
		elif self.modelType == 16:
			self.loadStart16(bs)
			self.baseOffset  = 0x3C
		
		for a in range(0, self.matCount):
			bs.seek(self.baseOffset, NOESEEK_ABS)
			matInfo = bs.read("6i")
			self.baseOffset = bs.tell()
			#print("Loading Material " + str(a))
			self.loadMaterial(bs, matInfo)
		
		fvfInfo = []
		for a in range(0, self.fvfCount):
			bs.seek(self.baseOffset, NOESEEK_ABS)
			fvfInfo.append(bs.read("4i"))
			self.baseOffset = bs.tell()

		for a in range(0, self.bufferCount):
			bs.seek(self.baseOffset, NOESEEK_ABS)
			bufferInfoOff = bs.readUInt()
			self.baseOffset = bs.tell()
			bs.seek(self.dataStart + self.matGroupStart + (0x2C * a), NOESEEK_ABS)
			unkFloats = bs.read("8f")
			vertBuffIndex, matGroupCount, bufferInfo = (bs.read("3i"))
			self.loadFvfInfo(bs, fvfInfo[a])
			self.loadBufferInfo(bs, [vertBuffIndex, matGroupCount, bufferInfo])
		#print(self.baseOffset)	

	def loadStart04(self, bs):
		baseHeader = bs.read("5i")
		bs.seek(self.dataStart + baseHeader[0], NOESEEK_ABS)
		bs.seek(self.dataStart + baseHeader[1], NOESEEK_ABS)
		scenenameOff, sceneHash, self.matCount = bs.read("3i")
		bs.seek(self.dataStart + baseHeader[2], NOESEEK_ABS)
		matStart, self.fvfCount = bs.read("2i")
		bs.seek(self.dataStart + baseHeader[3], NOESEEK_ABS)
		floatStart, self.bufferCount = bs.read("2i")
		bs.seek(self.dataStart + baseHeader[4], NOESEEK_ABS)
		self.matGroupStart, Null = bs.read("2i")

	def loadStart16(self, bs):
		baseHeader = bs.read("7i")
		bs.seek(self.dataStart + baseHeader[0], NOESEEK_ABS)
		bs.seek(self.dataStart + baseHeader[1], NOESEEK_ABS)
		self.boneInfoStart, boneFlag = bs.read("2i")
		bs.seek(self.dataStart + baseHeader[2], NOESEEK_ABS)
		bs.seek(self.dataStart + baseHeader[3], NOESEEK_ABS)
		scenenameOff, sceneHash, self.matCount = bs.read("3i")
		bs.seek(self.dataStart + baseHeader[4], NOESEEK_ABS)
		matStart, self.fvfCount = bs.read("2i")
		bs.seek(self.dataStart + baseHeader[5], NOESEEK_ABS)
		floatStart, self.bufferCount = bs.read("2i")
		bs.seek(self.dataStart + baseHeader[6], NOESEEK_ABS)
		self.matGroupStart, Null = bs.read("2i")
		self.loadBone(bs)
		
	def loadBone(self, bs):
		bs.seek(self.dataStart + self.boneInfoStart, NOESEEK_ABS)
		boneCount, boneNameCount, boneStart = bs.read("3i")
		for a in range(0, boneCount):
			bs.seek(self.dataStart + boneStart + (0x80 * a), NOESEEK_ABS)
			boneNameOff, boneHash, boneParent, boneUnk = bs.read("4i")
			boneMtx = NoeMat44.fromBytes(bs.readBytes(64)).toMat43().inverse()
			bs.seek(self.dataStart + boneNameOff, NOESEEK_ABS)
			boneName = bs.readString()
			newBone = NoeBone(a, boneName, boneMtx, None, boneParent)
			self.boneList.append(newBone)

	def loadMaterial(self, bs, matInfo):
		bs.seek(self.dataStart + matInfo[0], NOESEEK_ABS)
		nameOff, hash = bs.read("2i")
		bs.seek(self.dataStart + nameOff, NOESEEK_ABS)
		#print(bs.readString())#labsGenericVertColors

		bs.seek(self.dataStart + matInfo[1], NOESEEK_ABS)
		nameOff, hash, unk, propCount = bs.read("4i")
		bs.seek(self.dataStart + nameOff, NOESEEK_ABS)
		material = NoeMaterial(bs.readString(), "")

		bs.seek(self.dataStart + matInfo[2], NOESEEK_ABS)
		propInfo, floatCount = bs.read("2i")

		bs.seek(self.dataStart + matInfo[3], NOESEEK_ABS)
		floatStart, texCount = bs.read("2i")
		for a in range(0, propCount):
			bs.seek(self.dataStart + propInfo + (a * 16), NOESEEK_ABS)
			propName, prophash, propStart, usedFloat = bs.read("4i")
			bs.seek(self.dataStart + propName, NOESEEK_ABS)
			valueName = bs.readString()#prop name
			bs.seek(self.dataStart + floatStart + (propStart * 4), NOESEEK_ABS)
			propValue = bs.read(usedFloat * "f")
			if valueName in materialLoaderDict:
				materialLoaderDict[valueName](material, propValue)
				#print("New Material Found:",[valueName, propValue])
			else:
				pass
				#print("New Material Found:",[valueName, propValue])

		bs.seek(self.dataStart + matInfo[4], NOESEEK_ABS)
		texStart, fvfCount = bs.read("2i")
		for a in range(0, texCount):
			bs.seek(self.dataStart + texStart + (a * 16), NOESEEK_ABS)
			texTypeName, texTypeHash, texName, texHash = bs.read("4i")
			bs.seek(self.dataStart + texTypeName, NOESEEK_ABS)
			texTypeName = bs.readString()#texTypeName name
			bs.seek(self.dataStart + texName, NOESEEK_ABS)
			texName = bs.readString()#texName
			if texTypeName in materialLoaderDict:
				materialLoaderDict[texTypeName](self, material, texName)
				#print("New Material Found:",[texTypeName, texName])
			else:
				pass
				#print("New Material Found:",[texTypeName, texName])

		bs.seek(self.dataStart + matInfo[5], NOESEEK_ABS)
		fvfStart = bs.readUInt()
		for a in range(0, fvfCount):
			bs.seek(self.dataStart + fvfStart + (a * 16), NOESEEK_ABS)
			fvfTypeName, fvfTypeHash, fvfName, fvfHash = bs.read("4i")
			bs.seek(self.dataStart + fvfTypeName, NOESEEK_ABS)
			fvfPart = bs.readString()#fvfTypeName name
			bs.seek(self.dataStart + fvfName, NOESEEK_ABS)
			fvfSlot = bs.readString()#fvfName
		self.matList.append(material)

	def loadFvfInfo(self, bs, fvfInfo):
		bs.seek(self.dataStart + fvfInfo[0], NOESEEK_ABS)
		polyNameOff, hash, null, fvfUnkCount = bs.read("4i")
		bs.seek(self.dataStart + polyNameOff, NOESEEK_ABS)
		#print(bs.readString())#poly name

		bs.seek(self.dataStart + fvfInfo[1], NOESEEK_ABS)
		vertStructOff = bs.readUInt()
		bs.seek(self.dataStart + fvfInfo[2], NOESEEK_ABS)
		fvfTmpCount = (bs.readUInt() - vertStructOff) // 8
		bs.seek(self.dataStart + vertStructOff, NOESEEK_ABS)
		fvfTemp = []
		for a in range(0, fvfTmpCount):
			fvfData = bs.read("2b3H")
			fvfTemp.append(fvfData)

		bs.seek(self.dataStart + fvfInfo[2], NOESEEK_ABS)
		vertStart = bs.readUInt()
		#print(vertStart)

		bs.seek(self.dataStart + fvfInfo[3], NOESEEK_ABS)
		self.faceStart, vertCount, faceCount = bs.read("3i")
		self.vertSize = (self.faceStart - vertStart) // vertCount
		#print([self.faceStart, vertCount, faceCount, self.vertSize])

		bs.seek(self.dataStart + vertStart, NOESEEK_ABS)
		vertBuff = bs.readBytes(vertCount * self.vertSize)

		for a in range(0, fvfTmpCount):
			if str(fvfTemp[a][4]) in fvfPartLoaderDict:
				fvfPartLoaderDict[str(fvfTemp[a][4])](self, fvfTemp[a], vertBuff)
				#print("New fvf Type Found:", fvfTemp[a])
			else:
				pass
				#print("New fvf Type Found:", fvfTemp[a])
		

	def loadBufferInfo(self, bs, bufferInfo):
		#print(bufferInfo)
		bs.seek(self.dataStart + bufferInfo[2], NOESEEK_ABS)
		for a in range(0, bufferInfo[1]):
			bs.seek(self.dataStart + bufferInfo[2] + (a * 0x6C), NOESEEK_ABS)
			bs.read("8f")
			facePos, faceCount, matID, unkID = bs.read("2i2h")
			#print(["mat id",bs.tell(),matID])
			bs.seek(self.dataStart + self.faceStart + (2 * facePos), NOESEEK_ABS)
			faceBuff = bs.readBytes(faceCount * 2)
			rapi.rpgSetMaterial(self.matList[matID].name)
			rapi.rpgCommitTriangles(faceBuff, noesis.RPGEODATA_USHORT, faceCount, noesis.RPGEO_TRIANGLE, 1)



	def load_Position(self, fvfData, vertBuff):
		if fvfData[0] != -1:
			rapi.rpgBindPositionBufferOfs(vertBuff, noesis.RPGEODATA_FLOAT, self.vertSize, fvfData[2])

	def load_UV0(self, fvfData, vertBuff):
		if fvfData[0] != -1:
			if fvfData[3] != 1:
				rapi.rpgBindUV1BufferOfs(vertBuff, noesis.RPGEODATA_SHORT, self.vertSize, fvfData[2])
			if fvfData[3] != 9:
				rapi.rpgBindUV1BufferOfs(vertBuff, noesis.RPGEODATA_FLOAT, self.vertSize, fvfData[2])

	def load_Normal(self, fvfData, vertBuff):
		pass

	def load_Tangent0(self, fvfData, vertBuff):
		pass

	def load_Color0(self, fvfData, vertBuff):
		if fvfData[0] != -1:
			rapi.rpgBindColorBufferOfs(vertBuff, noesis.RPGEODATA_UBYTE, self.vertSize, fvfData[2], 4)

	def load_Index(self, fvfData, vertBuff):
		rapi.rpgBindBoneIndexBufferOfs(vertBuff, noesis.RPGEODATA_UBYTE, self.vertSize, fvfData[2], 4)

	def load_Weight(self, fvfData, vertBuff):
		rapi.rpgBindBoneWeightBufferOfs(vertBuff, noesis.RPGEODATA_UBYTE, self.vertSize, fvfData[2], 4)

	def load_BiNormal0(self, fvfData, vertBuff):
		pass

fvfPartLoaderDict = {
	"0"			: bmdlFile.load_Position,
	"1"			: bmdlFile.load_Normal,
	"2"			: bmdlFile.load_Tangent0,
	"4"			: bmdlFile.load_UV0,
	"5"			: bmdlFile.load_Color0,
	"6"			: bmdlFile.load_Weight,
	"7"			: bmdlFile.load_Index,
	"P"			: bmdlFile.load_BiNormal0
}
#Noesis blends:
#0 - "None"
#1 - "GL_ZERO"
#2 - "GL_ONE"
#3 - "GL_SRC_COLOR"
#4 - "GL_ONE_MINUS_SRC_COLOR"
#5 - "GL_SRC_ALPHA"
#6 - "GL_ONE_MINUS_SRC_ALPHA"
#7 - "GL_DST_ALPHA"
#8 - "GL_ONE_MINUS_DST_ALPHA"
#9 - "GL_DST_COLOR"
#10 - "GL_ONE_MINUS_DST_COLOR"
#11 - "GL_SRC_ALPHA_SATURATE"
class Material:

	def load_DiffuseTint(self, floats):
		self.setDiffuseColor(NoeVec4([floats[0], floats[1], floats[2], 0]))
		self.setFlags(noesis.NMATFLAG_TWOSIDED, 1)
		self.setDefaultBlend(0)
		self.setFlags(0, 1)

	def load_SpecularTint(self, floats):
		self.setSpecularColor(NoeVec4([floats[0], floats[1], floats[2], 0]))
		#print(floats)

	def load_OffsetUV(self, floats):
		pass
		#print(floats)

	def load_TileUV(self, floats):
		pass
		#print(floats)

	def load_AmbiLevel(self, floats):
		pass
		#print(floats)

	def load_EmissiveLevel(self, floats):
		pass
		#print(floats)

	def load_GlowLevel(self, floats):
		pass
		#print(floats)

	def load_NormalLevel(self, floats):
		pass
		#print(floats)

	def load_ScrollUV(self, floats):
		pass
		#print(floats)

	def load_Delay(self, floats):
		pass
		#print(floats)

	def load_Rate(self, floats):
		pass
		#print(floats)

	def load_diffuseMap(self, material, texName):
		Material.load_textureFile(self, texName)
		material.setTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_normalMap(self, material, texName):
		Material.load_textureFile(self, texName)
		material.setNormalTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_specularMap(self, material, texName):
		Material.load_textureFile(self, texName)
		material.setSpecularTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_envMap(self, material, texName):
		Material.load_textureFile(self, texName)
		material.setEnvTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_diffuseInteriorMap(self, material, texName):
		Material.load_textureFile(self, texName)
		#material.setTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_normalInteriorMap(self, material, texName):
		Material.load_textureFile(self, texName)
		#material.setTexture(rapi.getExtensionlessName(rapi.getLocalFileName(texName)))

	def load_textureFile(self, texName):
		folderName = rapi.getDirForFilePath(rapi.getInputName())
		folderName = folderName.replace('\\', '/')
		folderName = (folderName + "../../../../")
		if (rapi.checkFileExists(folderName + texName)):
			texData = rapi.loadIntoByteArray(folderName + texName)
			texture = rapi.loadTexByHandler(texData, ".dds")
			texture.name = rapi.getExtensionlessName(rapi.getLocalFileName(texName))
			self.texList.append(texture)

materialLoaderDict = {
	"DiffuseTint"			: Material.load_DiffuseTint,
	"SpecularTint"			: Material.load_SpecularTint,
	"OffsetUV"			: Material.load_OffsetUV,
	"TileUV"			: Material.load_TileUV,
	"AmbiLevel"			: Material.load_AmbiLevel,
	"EmissiveLevel"			: Material.load_EmissiveLevel,
	"GlowLevel"			: Material.load_GlowLevel,
	"NormalLevel"			: Material.load_NormalLevel,
	"ScrollUV"			: Material.load_ScrollUV,
	"Delay"				: Material.load_Delay,
	"Rate"				: Material.load_Rate,
	"diffuseMap"			: Material.load_diffuseMap,
	"normalMap"			: Material.load_normalMap,
	"specularMap"			: Material.load_specularMap,
	"envMap"			: Material.load_envMap,
	"diffuseInteriorMap"		: Material.load_diffuseInteriorMap,
	"normalInteriorMap"		: Material.load_normalInteriorMap
}




def bmdlmodLoadModel(data, mdlList):
	ctx = rapi.rpgCreateContext()
	bmdl = bmdlFile(NoeBitStream(data))
	bmdl.loadAll(bmdl.bs)
	rapi.setPreviewOption("setAngOfs", "0 90 0")
	try:
		mdl = rapi.rpgConstructModel()
	except:
		mdl = NoeModel()
	mdl.setModelMaterials(NoeModelMaterials(bmdl.texList, bmdl.matList))
	mdlList.append(mdl); mdl.setBones(bmdl.boneList)	
	return 1