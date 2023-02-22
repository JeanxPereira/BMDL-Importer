#include "stdafx.h"
#include "ue2_pskpsa.h"

//checks for psk/psa skeleton format restrictions
static bool Model_PSK_SkeletonIsAcceptable(modelBone_t *bones, int numBones)
{
	if (bones->eData.parent)
	{ //can't support first bone that isn't a root
		return false;
	}
	int numRoots = 0;
	for (int i = 0; i < numBones; i++)
	{
		modelBone_t *bone = bones+i;
		if (!bone->eData.parent || bone->eData.parent == bone)
		{
			numRoots++;
		}
		if (bone->eData.parent && bone->eData.parent->index > bone->index)
		{ //bones must be in order
			return false;
		}
	}
	return (numRoots == 1);
}

//qsort compare function
static int Model_PSK_BoneCompare(const modelBone_t *a, const modelBone_t *b)
{
	if (a->eData.parent && !b->eData.parent)
	{
		return 1;
	}
	if (b->eData.parent && !a->eData.parent)
	{
		return -1;
	}

	if (a->index > b->index)
	{
		return 1;
	}
	if (b->index > a->index)
	{
		return -1;
	}

	return 0;
}

//sort the skeleton and re-parent root bones (compensating animation matrices, if applicable)
static int *Model_PSK_SortSkeleton(modelBone_t *bones, int numBones, RichMat43 *amats, int numFrames, noeRAPI_t *rapi)
{
	int *boneMap = rapi->Noesis_QSortBones(bones, numBones, Model_PSK_BoneCompare, true);
	if (amats && numFrames > 0)
	{ //remap anims
		RichMat43 *tmpMats = (RichMat43 *)rapi->Noesis_UnpooledAlloc(sizeof(RichMat43)*numBones);
		for (int i = 0; i < numFrames; i++)
		{
			RichMat43 *frameMats = amats+i*numBones;
			for (int j = 0; j < numBones; j++)
			{
				tmpMats[boneMap[j]] = frameMats[j];
			}
			memcpy(frameMats, tmpMats, sizeof(RichMat43)*numBones);
		}
		rapi->Noesis_UnpooledFree(tmpMats);
	}

	if (bones->eData.parent)
	{ //this should never happen, unless parent pointers are broken and pointing outside of the main bone list
		rapi->LogOutput("ERROR: Ended up with a non-root bone at index 0!");
		return NULL;
	}

	//re-parent all subsequent root bones to the single root bone
	for (int i = 1; i < numBones; i++)
	{
		modelBone_t *bone = bones+i;
		if (!bone->eData.parent)
		{
			bone->eData.parent = &bones[0];
			if (amats && numFrames > 0)
			{ //make all frames for this bone relative to the new parent
				for (int j = 0; j < numFrames; j++)
				{
					RichMat43 *frameMats = amats+j*numBones;
					frameMats[i] = frameMats[i] * frameMats[0].GetInverse();
				}
			}
		}
	}
	return boneMap;
}

//export PSK
bool Model_PSK_Write(noesisModel_t *mdl, RichBitStream *outStream, noeRAPI_t *rapi)
{
	const int exportVer = 0x1e9179;
	sharedModel_t *pmdl = rapi->rpgGetSharedModel(mdl,
													NMSHAREDFL_WANTGLOBALARRAY | //calculate giant flat vertex/triangle arrays
													NMSHAREDFL_FLATWEIGHTS | //create flat vertex weight arrays
													NMSHAREDFL_FLATWEIGHTS_FORCE4 | //force 4 weights per vert for the flat weight array data
													NMSHAREDFL_REVERSEWINDING //reverse the face winding (as per UT) - most formats will not want you to do this!
													);
	if (!pmdl || pmdl->numAbsTris <= 0 || pmdl->numAbsVerts <= 0)
	{
		rapi->LogOutput("ERROR: Failed to grab valid geometry data for export.\n");
		return false;
	}
	if (pmdl->numAbsVerts >= 65536)
	{
		rapi->LogOutput("WARNING: Number of absolute vertices exceeds PSK format range!");
	}

	//create a materials list
	int numMaterials = pmdl->numMeshes;
	pskMaterial_t *materials = (pskMaterial_t *)rapi->Noesis_UnpooledAlloc(sizeof(pskMaterial_t)*numMaterials);
	for (int i = 0; i < pmdl->numMeshes; i++)
	{
		sharedMesh_t *mesh = pmdl->meshes+i;

		pskMaterial_t &matDst = materials[i];
		memset(&matDst, 0, sizeof(matDst));
		strncpy_s(matDst.name, 64, mesh->skinName, 63);
	}
	int *materialMap = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*numMaterials);
	pskMaterial_t *nmat = (pskMaterial_t *)rapi->Noesis_GetUniqueElements(materials, sizeof(pskMaterial_t), sizeof(pskMaterial_t), numMaterials, materialMap);
	rapi->Noesis_UnpooledFree(materials);
	materials = nmat;

	modelBone_t *bones = pmdl->bones;
	int numBones = pmdl->numBones;
	if (!bones || numBones <= 0)
	{ //create a placeholder bone
		numBones = 1;
		bones = rapi->Noesis_AllocBones(1);
		strncpy_s(bones->name, 32, "root", 32);
		bones->mat = g_identityMatrix;
	}

	int *boneMap = NULL;
	if (!Model_PSK_SkeletonIsAcceptable(bones, numBones))
	{
		rapi->LogOutput("WARNING: Found more than one root bone, re-parenting roots.\n");
		bones = rapi->Noesis_CopyBones(bones, numBones); //don't want to modify the data which may be shared internally with noesis
		boneMap = Model_PSK_SortSkeleton(bones, numBones, NULL, 0, rapi);
	}

	//fill in a global position array
	pskPosW_t *absVPos = (pskPosW_t *)rapi->Noesis_UnpooledAlloc(sizeof(pskPosW_t)*pmdl->numAbsVerts);
	memset(absVPos, 0, sizeof(pskPosW_t)*pmdl->numAbsVerts);
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		sharedVMap_t *vm = pmdl->absVertMap+i;
		sharedMesh_t *mesh = pmdl->meshes+vm->meshIdx;
		modelVert_t *vert = mesh->verts+vm->vertIdx;
		absVPos[i].v[0] = vert->x;
		absVPos[i].v[1] = vert->y;
		absVPos[i].v[2] = vert->z;
		if (mesh->flatBoneIdx && mesh->flatBoneWgt)
		{
			int *boneIdx = mesh->flatBoneIdx + mesh->numWeightsPerVert*vm->vertIdx;
			float *boneWgt = mesh->flatBoneWgt + mesh->numWeightsPerVert*vm->vertIdx;
			for (int j = 0; j < 4 && j < mesh->numWeightsPerVert; j++)
			{
				absVPos[i].boneIdx[j] = boneIdx[j];
				absVPos[i].boneWgt[j] = boneWgt[j];
			}
		}
	}
	//allocate an index map and create a list of unique vertex positions
	int *vposMap = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*pmdl->numAbsVerts);
	int numVPos = pmdl->numAbsVerts;
	pskPosW_t *vpos = (pskPosW_t *)rapi->Noesis_GetUniqueElements(absVPos, sizeof(pskPosW_t), sizeof(pskPosW_t), numVPos, vposMap);
	rapi->Noesis_UnpooledFree(absVPos); //no longer need the absolute vert list
	if (numVPos >= 65536)
	{
		rapi->LogOutput("WARNING: Number of unique positions exceeds PSK format range!");
	}

	//create a weight list
	CArrayList<pskWeight_t> weightList;
	int *vposWeightFlags = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*numVPos);
	memset(vposWeightFlags, 0, sizeof(int)*numVPos);
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		sharedVMap_t *vm = pmdl->absVertMap+i;
		sharedMesh_t *mesh = pmdl->meshes+vm->meshIdx;
		int vposIdx = vposMap[i];
		if (vposWeightFlags[vposIdx])
		{ //already gathered weights for the associated position, they must be duplicated
			continue;
		}
		vposWeightFlags[vposIdx] = 1;
		if (mesh->flatBoneIdx && mesh->flatBoneWgt)
		{
			int *boneIdx = mesh->flatBoneIdx + mesh->numWeightsPerVert*vm->vertIdx;
			float *boneWgt = mesh->flatBoneWgt + mesh->numWeightsPerVert*vm->vertIdx;
			for (int j = 0; j < mesh->numWeightsPerVert; j++)
			{
				if (boneWgt[j] > 0.0f && boneIdx[j] >= 0 && boneIdx[j] < numBones)
				{ //don't bother adding 0-influence weights
					pskWeight_t weightDst;
					memset(&weightDst, 0, sizeof(weightDst));
					weightDst.w = boneWgt[j];
					weightDst.boneIdx = (boneMap) ? boneMap[boneIdx[j]] : boneIdx[j];
					weightDst.pointIdx = vposIdx;
					weightList.Append(weightDst);
				}
			}
		}
		else
		{ //stub weight
			pskWeight_t weightDst;
			memset(&weightDst, 0, sizeof(weightDst));
			weightDst.w = 1.0f;
			weightDst.pointIdx = vposIdx;
			weightDst.boneIdx = 0;
			weightList.Append(weightDst);
		}
	}
	rapi->Noesis_UnpooledFree(vposWeightFlags);

	//fill in bone children counts
	int *boneChildren = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*numBones);
	memset(boneChildren, 0, sizeof(int)*numBones);
	for (int i = 0; i < numBones; i++)
	{
		modelBone_t *bone = bones+i;
		if (bone->eData.parent)
		{
			boneChildren[bone->eData.parent->index]++;
		}
	}

	//make a list of psk verts, then cull duplicates out
	pskVert_t *pskVertsPreCull = (pskVert_t *)rapi->Noesis_UnpooledAlloc(sizeof(pskVert_t)*pmdl->numAbsVerts);
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		sharedVMap_t *vm = pmdl->absVertMap+i;
		sharedMesh_t *mesh = pmdl->meshes+vm->meshIdx;
		modelTexCoord_t *tc = mesh->uvs+vm->vertIdx;
		int pointIdx = vposMap[i];

		pskVert_t &vertDst = pskVertsPreCull[i];
		memset(&vertDst, 0, sizeof(vertDst));
		vertDst.matIdx = materialMap[vm->meshIdx];
		vertDst.pointIdx = (WORD)pointIdx;
		vertDst.tc[0] = tc->u;
		vertDst.tc[1] = tc->v;
	}
	int numPskVerts = pmdl->numAbsVerts;
	int *pskVertMap = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*pmdl->numAbsVerts);
	pskVert_t *pskVerts = (pskVert_t *)rapi->Noesis_GetUniqueElements(pskVertsPreCull, sizeof(pskVert_t), sizeof(pskVert_t), numPskVerts, pskVertMap);
	rapi->Noesis_UnpooledFree(pskVertsPreCull); //no longer need the pre-culled vert list
	rapi->LogOutput("Culled %i verts.\n", pmdl->numAbsVerts-numPskVerts);

	pskChunk_t chunk;
	memset(&chunk, 0, sizeof(chunk));

	//write header
	strncpy_s(chunk.id, 20, "ACTRHEAD", 20);
	chunk.version = exportVer;
	outStream->WriteBytes(&chunk, sizeof(chunk));

	//write points
	strncpy_s(chunk.id, 20, "PNTS0000", 20);
	chunk.numRec = numVPos;
	chunk.recSize = sizeof(RichVec3);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < numVPos; i++)
	{
		outStream->WriteBytes(&vpos[i].v, sizeof(vpos[i].v));
	}

	//write vertices
	strncpy_s(chunk.id, 20, "VTXW0000", 20);
	chunk.numRec = numPskVerts;
	chunk.recSize = sizeof(pskVert_t);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	outStream->WriteBytes(pskVerts, sizeof(pskVert_t)*numPskVerts);

	//write faces
	strncpy_s(chunk.id, 20, "FACE0000", 20);
	chunk.numRec = pmdl->numAbsTris;
	chunk.recSize = sizeof(pskFace_t);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < pmdl->numAbsTris; i++)
	{
		modelLongTri_t *tri = pmdl->absTris+i;

		pskFace_t faceDst;
		memset(&faceDst, 0, sizeof(faceDst));
		faceDst.idx[0] = (WORD)pskVertMap[tri->idx[0]];
		faceDst.idx[1] = (WORD)pskVertMap[tri->idx[1]];
		faceDst.idx[2] = (WORD)pskVertMap[tri->idx[2]];
		sharedVMap_t *vm = pmdl->absVertMap+tri->idx[0]; //use the material from the mesh for the first vert on the face (faces cannot use verts from different meshes)
		faceDst.matIdx = materialMap[vm->meshIdx];
		faceDst.group = 1; //todo - check normals along triangle edges to determine smooth groups
		outStream->WriteBytes(&faceDst, sizeof(faceDst));
	}

	//write materials
	strncpy_s(chunk.id, 20, "MATT0000", 20);
	chunk.numRec = numMaterials;
	chunk.recSize = sizeof(pskMaterial_t);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	outStream->WriteBytes(materials, sizeof(pskMaterial_t)*numMaterials);

	//write skeleton
	strncpy_s(chunk.id, 20, "REFSKELT", 20);
	chunk.numRec = numBones;
	chunk.recSize = sizeof(pskBone_t);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < numBones; i++)
	{
		modelBone_t *bone = bones+i;

		pskBone_t boneDst;
		memset(&boneDst, 0, sizeof(boneDst));
		strncpy_s(boneDst.name, 64, bone->name, 64);
		boneDst.numChildren = boneChildren[i];
		boneDst.parent = (bone->eData.parent) ? bone->eData.parent->index : i;
		//psk bones are parent-relative, so multiply the bone matrices by their parent's inverse when applicable
		RichMat43 boneMat = bone->mat;
		if (bone->eData.parent)
		{
			boneMat = boneMat * RichMat43(bone->eData.parent->mat).GetInverse();
		}
		boneDst.trans = boneMat[3];
		boneDst.rot = boneMat.GetTranspose().ToQuat();
		if (bone->eData.parent)
		{ //flip handedness to ut
			boneDst.rot[0] = -boneDst.rot[0];
			boneDst.rot[1] = -boneDst.rot[1];
			boneDst.rot[2] = -boneDst.rot[2];
		}
		outStream->WriteBytes(&boneDst, sizeof(boneDst));
	}

	//write weights
	strncpy_s(chunk.id, 20, "RAWWEIGHTS", 20);
	chunk.numRec = weightList.Num();
	chunk.recSize = sizeof(pskWeight_t);
	outStream->WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < weightList.Num(); i++)
	{
		pskWeight_t &weight = weightList[i];
		outStream->WriteBytes(&weight, sizeof(weight));
	}

	//all done, free up the temp buffers
	rapi->Noesis_UnpooledFree(pskVertMap);
	rapi->Noesis_UnpooledFree(pskVerts);
	rapi->Noesis_UnpooledFree(vpos);
	rapi->Noesis_UnpooledFree(vposMap);
	rapi->Noesis_UnpooledFree(boneChildren);
	rapi->Noesis_UnpooledFree(materials);
	rapi->Noesis_UnpooledFree(materialMap);
	return true;
}

//export PSA
void Model_PSA_Write(noesisAnim_t *anim, noeRAPI_t *rapi)
{
	const int exportVer = 0x1e9179;
	int numFrames = 0;
	float frameRate = 0.0f;
	int numBones = 0;
	modelBone_t *abInfo = NULL;
	RichMat43 *amats = (RichMat43 *)rapi->rpgMatsAndInfoFromAnim(anim, numFrames, frameRate, &numBones, &abInfo, true);
	if (!amats || numFrames <= 0 || numBones <= 0 || !abInfo)
	{
		rapi->LogOutput("ERROR: Could not obtain bone/anim data for export.\n");
		return;
	}

	if (!Model_PSK_SkeletonIsAcceptable(abInfo, numBones))
	{
		rapi->LogOutput("WARNING: Found more than one root bone, re-parenting roots.\n");
		abInfo = rapi->Noesis_CopyBones(abInfo, numBones); //don't want to modify the data which may be shared internally with noesis
		Model_PSK_SortSkeleton(abInfo, numBones, amats, numFrames, rapi);
	}

	RichBitStream bs;
	pskChunk_t chunk;
	memset(&chunk, 0, sizeof(chunk));

	//write header
	strncpy_s(chunk.id, 20, "ANIMHEAD", 20);
	chunk.version = exportVer;
	bs.WriteBytes(&chunk, sizeof(chunk));

	//write bones
	strncpy_s(chunk.id, 20, "BONENAMES", 20);
	chunk.numRec = numBones;
	chunk.recSize = sizeof(pskBone_t);
	bs.WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < numBones; i++)
	{
		pskBone_t boneDst;
		modelBone_t *boneSrc = abInfo+i;

		memset(&boneDst, 0, sizeof(boneDst));
		strncpy_s(boneDst.name, 64, boneSrc->name, 64);
		boneDst.parent = (boneSrc->eData.parent) ? boneSrc->eData.parent->index : i;
		//anim format doesn't seem to care about any other field for bones

		bs.WriteBytes(&boneDst, sizeof(boneDst));
	}

	//write anim infos
	int numAnimSeq = (anim->aseq && anim->aseq->numSeq > 0) ? anim->aseq->numSeq : 1;
	strncpy_s(chunk.id, 20, "ANIMINFO", 20);
	chunk.numRec = numAnimSeq;
	chunk.recSize = sizeof(psaAnimInfo_t);
	bs.WriteBytes(&chunk, sizeof(chunk));
	if (anim->aseq && anim->aseq->numSeq > 0)
	{ //write preserved sequence data
		for (int i = 0; i < numAnimSeq; i++)
		{
			noesisASeq_t *seq = anim->aseq->s+i;
			char *seqName = (seq->name) ? seq->name : "UnknownSequence";
			int numSeqFrames = (seq->endFrame-seq->startFrame)+1;

			psaAnimInfo_t ainfo;
			memset(&ainfo, 0, sizeof(ainfo));
			strncpy_s(ainfo.name, 64, seqName, 64);
			strncpy_s(ainfo.group, 64, "None", 64);
			ainfo.numBones = numBones;
			ainfo.keyNum = numSeqFrames*numBones;
			ainfo.duration = (float)numSeqFrames;
			ainfo.frameRate = seq->frameRate;
			ainfo.firstFrame = seq->startFrame;
			ainfo.numFrames = numSeqFrames;
			bs.WriteBytes(&ainfo, sizeof(ainfo));
		}
	}
	else
	{ //just spit out a single sequence for all of the frames
		psaAnimInfo_t ainfo;
		memset(&ainfo, 0, sizeof(ainfo));
		strncpy_s(ainfo.name, 64, "AllFrames", 64);
		strncpy_s(ainfo.group, 64, "None", 64);
		ainfo.numBones = numBones;
		ainfo.keyNum = numFrames*numBones;
		ainfo.duration = (float)numFrames;
		ainfo.frameRate = 20.0f;
		ainfo.numFrames = numFrames;
		bs.WriteBytes(&ainfo, sizeof(ainfo));
	}

	//write anim keys
	strncpy_s(chunk.id, 20, "ANIMKEYS", 20);
	chunk.numRec = numFrames*numBones;
	chunk.recSize = sizeof(psaAnimKey_t);
	bs.WriteBytes(&chunk, sizeof(chunk));
	for (int i = 0; i < chunk.numRec; i++)
	{
		modelBone_t *bone = abInfo+(i%numBones);
		RichMat43 &amat = amats[i];
		psaAnimKey_t akey;
		memset(&akey, 0, sizeof(akey));

		akey.frameTime = 1.0f;
		akey.trans = amat[3];
		akey.rot = amat.GetTranspose().ToQuat();
		if (bone->eData.parent)
		{ //flip handedness to ut
			akey.rot[0] = -akey.rot[0];
			akey.rot[1] = -akey.rot[1];
			akey.rot[2] = -akey.rot[2];
		}
		bs.WriteBytes(&akey, sizeof(akey));
	}

	//all done, spit it out
	int size = bs.GetSize();
	rapi->Noesis_WriteAnimFile(anim->filename, ".psa", (BYTE *)bs.GetBuffer(), size);
}
