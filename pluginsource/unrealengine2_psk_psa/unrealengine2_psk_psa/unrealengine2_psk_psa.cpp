//General requirements and/or suggestions for Noesis plugins:
//
// -Use 1-byte struct alignment for all shared structures. (plugin MSVC project file defaults everything to 1-byte-aligned)
// -Always clean up after yourself. Your plugin stays in memory the entire time Noesis is loaded, so you don't want to crap up the process heaps.
// -Try to use reliable type-checking, to ensure your plugin doesn't conflict with other file types and create false-positive situations.
// -Really try not to write crash-prone logic in your data check function! This could lead to Noesis crashing from trivial things like the user browsing files.
// -When using the rpg begin/end interface, always make your Vertex call last, as it's the function which triggers a push of the vertex with its current attributes.
// -!!!! Check the web site and documentation for updated suggestions/info! !!!!

#include "stdafx.h"
#include "ue2_pskpsa.h"

extern bool Model_PSK_Write(noesisModel_t *mdl, RichBitStream *outStream, noeRAPI_t *rapi);
extern void Model_PSA_Write(noesisAnim_t *anim, noeRAPI_t *rapi);

const char *g_pPluginName = "unrealengine2_psk_psa";
const char *g_pPluginDesc = "Unreal ActorX PSK+PSA handler, by Dick.";

pskOpts_t *g_opts = NULL;

//is it this format?
bool Model_PSK_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(pskChunk_t))
	{
		return false;
	}
	pskChunk_t *chunk = (pskChunk_t *)fileBuffer;
	if (memcmp(chunk->id, "ACTRHEAD", 8))
	{
		return false;
	}
	/*
	if (chunk->version != 0x1e83b9 && chunk->version != 0x1e9179 && chunk->version != 0x2e)
	{
		return false;
	}
	*/
	int size = chunk->recSize*chunk->numRec;
	if (size < 0 || size > bufferLen)
	{
		return false;
	}
	return true;
}

//is it this format?
bool Model_PSA_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(pskChunk_t))
	{
		return false;
	}
	pskChunk_t *chunk = (pskChunk_t *)fileBuffer;
	if (memcmp(chunk->id, "ANIMHEAD", 8))
	{
		return false;
	}
	/*
	if (chunk->version != 0x1e83b9 && chunk->version != 0x1e9179 && chunk->version != 0x2e)
	{
		return false;
	}
	*/
	int size = chunk->recSize*chunk->numRec;
	if (size < 0 || size > bufferLen)
	{
		return false;
	}
	return true;
}

//convert bone data
static modelBone_t *Model_PSK_ConvertBones(pskBone_t *bones, int numBones, noeRAPI_t *rapi)
{
	modelBone_t *b = rapi->Noesis_AllocBones(numBones);
	for (int i = 0; i < numBones; i++)
	{
		modelBone_t *dst = b+i;
		pskBone_t *src = bones+i;
		int parIdx = (src->parent != i && src->parent >= 0) ? src->parent : -1;
		assert(parIdx < numBones);

		strncpy_s(dst->name, 31, src->name, 30);
		dst->name[31] = 0;
		if (!g_opts->keepBoneSpaces)
		{ //remove trailing spaces
			int lastSpace = -1;
			for (int j = 0; dst->name[j]; j++)
			{
				if (dst->name[j] == ' ')
				{
					if (lastSpace == -1)
					{
						lastSpace = j;
					}
				}
				else
				{
					lastSpace = -1;
				}
			}
			if (lastSpace > 0)
			{
				dst->name[lastSpace] = 0;
			}
		}
		dst->eData.parent = (parIdx >= 0) ? b+parIdx : NULL;
		RichQuat q = src->rot;
		if (dst->eData.parent)
		{ //flip handedness from ut
			q[0] = -q[0];
			q[1] = -q[1];
			q[2] = -q[2];
		}
		dst->mat = q.ToMat43(true).m;
		g_mfn->Math_VecCopy(src->trans.v, dst->mat.o);
	}
	rapi->rpgMultiplyBones(b, numBones);
	return b;
}

//create normals from the smoothing groups
static pskTriNrm_t *Model_PSK_CalculateSmoothGroups(pskFace_t *faces, int numFaces, pskVert_t *verts, int numVerts, RichVec3 *points, int numPoints, noeRAPI_t *rapi)
{
	pskTriPlane_t *planes = (pskTriPlane_t *)rapi->Noesis_UnpooledAlloc(sizeof(pskTriPlane_t)*numFaces);
	memset(planes, 0, sizeof(pskTriPlane_t)*numFaces);
	pskTriNrm_t *triNrms = (pskTriNrm_t *)rapi->Noesis_PooledAlloc(sizeof(pskTriNrm_t)*numFaces);
	memset(triNrms, 0, sizeof(pskTriNrm_t)*numFaces);

	//calculate the plane for each triangle
	for (int i = 0; i < numFaces; i++)
	{
		pskFace_t *face = faces+i;
		RichVec3 *pts[3];
		for (int j = 0; j < 3; j++)
		{
			pskVert_t *vert = verts+face->idx[j];
			pts[j] = points + vert->pointIdx;
		}

		pskTriPlane_t *plane = planes+i;
		g_mfn->Math_PlaneFromPoints(pts[2]->v, pts[1]->v, pts[0]->v, plane->p);
	}

#if 1 //use a reference list to avoid nested face iteration
	pskTriRefL_t *triRefs = (pskTriRefL_t *)rapi->Noesis_PooledAlloc(sizeof(pskTriRefL_t)*numPoints);
	memset(triRefs, 0, sizeof(pskTriRefL_t)*numPoints);
	for (int i = 0; i < numFaces; i++)
	{
		pskFace_t *face = faces+i;
		for (int j = 0; j < 3; j++)
		{
			int v1 = verts[face->idx[j]].pointIdx;
			pskTriRefL_t *refl = triRefs+v1;

			pskTriRef_t *triRef = (pskTriRef_t *)rapi->Noesis_PooledAlloc(sizeof(pskTriRef_t));
			memset(triRef, 0, sizeof(pskTriRef_t));
			triRef->triIdx = i;
			triRef->ptIdx = j;
			triRef->next = refl->refList;
			refl->numRefs++;
			refl->refList = triRef;
		}
	}
	for (int i = 0; i < numFaces; i++)
	{
		pskFace_t *face = faces+i;
		pskTriNrm_t *triNrm = triNrms+i;
		pskTriPlane_t *plane = planes+i;
		RichVec3 &planeNrm = *(RichVec3 *)plane->p;
		for (int k = 0; k < 3; k++)
		{
			int v1 = verts[face->idx[k]].pointIdx;
			pskTriRefL_t *refl = triRefs+v1;
			for (pskTriRef_t *triRef = refl->refList; triRef; triRef = triRef->next)
			{
				pskFace_t *otherFace = faces+triRef->triIdx;
				pskTriNrm_t *otherTriNrm = triNrms+triRef->triIdx;
				pskTriPlane_t *otherPlane = planes+triRef->triIdx;
				RichVec3 &otherPlaneNrm = *(RichVec3 *)otherPlane->p;
				if (!(face->group & otherFace->group) &&
					i != triRef->triIdx)
				{
					continue;
				}
				triNrm->nrm[k] += otherPlaneNrm;
			}
		}
	}
#else
	//add normals across faces which share points (fixme - build a reference list to make this faster.
	//or settle for per-vertex normals, so both nested iteration and vertex-triangle ref lists are unnecessary.
	//this may generally work fine for psk's, i don't know if vertices are normally pre-duplicated based on smoothing groups.)
	for (int i = 0; i < numFaces; i++)
	{
		pskFace_t *face = faces+i;
		pskTriNrm_t *triNrm = triNrms+i;
		pskTriPlane_t *plane = planes+i;
		RichVec3 &planeNrm = *(RichVec3 *)plane->p;
		triNrm->nrm[0] += planeNrm;
		triNrm->nrm[1] += planeNrm;
		triNrm->nrm[2] += planeNrm;
		for (int j = i+1; j < numFaces; j++)
		{
			pskFace_t *otherFace = faces+j;
			pskTriNrm_t *otherTriNrm = triNrms+j;
			pskTriPlane_t *otherPlane = planes+j;
			RichVec3 &otherPlaneNrm = *(RichVec3 *)otherPlane->p;
			if (!(face->group & otherFace->group))
			{
				continue;
			}
			for (int k = 0; k < 3; k++)
			{
				int v1 = verts[face->idx[k]].pointIdx;
				for (int l = 0; l < 3; l++)
				{
					int v2 = verts[otherFace->idx[l]].pointIdx;
					if (v1 == v2)
					{
						triNrm->nrm[k] += otherPlaneNrm;
						otherTriNrm->nrm[l] += planeNrm;
						break;
					}
				}
			}
		}
	}
#endif

	//normalize all of the results
	for (int i = 0; i < numFaces; i++)
	{
		pskTriNrm_t *triNrm = triNrms+i;
		triNrm->nrm[0].Normalize();
		triNrm->nrm[1].Normalize();
		triNrm->nrm[2].Normalize();
	}

	rapi->Noesis_UnpooledFree(planes);
	return triNrms;
}

//load it (note that you don't need to worry about validation here, if it was done in the Check function)
noesisModel_t *Model_PSK_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	RichVec3 *points = NULL;
	int numPoints = 0;
	pskVert_t *verts = NULL;
	int numVerts = 0;
	pskFace_t *faces = NULL;
	int numFaces = 0;
	pskMaterial_t *materials = NULL;
	int numMats = 0;
	pskBone_t *bones = NULL;
	int numBones = 0;
	pskWeight_t *weights = NULL;
	int numWeights = 0;

	int ofs = 0;
	while (ofs <= bufferLen-(int)sizeof(pskChunk_t))
	{
		pskChunk_t *chunk = (pskChunk_t *)(fileBuffer+ofs);
		if (!memcmp(chunk->id, "PNTS0000", 8))
		{ //points
			points = (RichVec3 *)(chunk+1);
			numPoints = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "VTXW0000", 8))
		{ //vertices
			verts = (pskVert_t *)(chunk+1);
			numVerts = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "FACE0000", 8))
		{ //faces
			faces = (pskFace_t *)(chunk+1);
			numFaces = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "MATT0000", 8))
		{ //materials
			materials = (pskMaterial_t *)(chunk+1);
			numMats = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "REFSKELT", 8))
		{ //skeleton
			bones = (pskBone_t *)(chunk+1);
			numBones = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "RAWWEIGHTS", 8))
		{ //weights
			weights = (pskWeight_t *)(chunk+1);
			numWeights = chunk->numRec;
		}
		//else, don't care

		int dataSize = chunk->recSize*chunk->numRec;
		if (dataSize < 0)
		{
			assert(0);
			break;
		}
		ofs += dataSize+sizeof(pskChunk_t);
	}
	if (!points || numPoints <= 0 || !verts || numVerts <= 0 ||
		!faces || numFaces <= 0)
	{
		rapi->LogOutput("ERROR: PSK did not contain any valid geometry chunks.\n");
		return NULL;
	}

	void *pgctx = rapi->rpgCreateContext();

	//associate vertex weights
	pskWList_t *wlist = NULL;
	if (bones && numBones > 0 && weights && numWeights > 0)
	{
		wlist = (pskWList_t *)rapi->Noesis_PooledAlloc(sizeof(pskWList_t)*numPoints);
		memset(wlist, 0, sizeof(pskWList_t)*numPoints);
		for (int i = 0; i < numWeights; i++)
		{
			pskWeight_t *weight = weights+i;
			pskWList_t *wv = wlist+weight->pointIdx;
			wv->numWeights++;
			pskWEntry_t *we = (pskWEntry_t *)rapi->Noesis_PooledAlloc(sizeof(pskWEntry_t));
			memset(we, 0, sizeof(pskWEntry_t));
			we->w = weight;
			we->next = wv->weights;
			wv->weights = we;
			assert(we->w->boneIdx >= 0 && we->w->boneIdx < numBones);
			assert(we->w->pointIdx >= 0 && we->w->pointIdx < numPoints);
		}
	}

	//get the normals
	pskTriNrm_t *triNrms = Model_PSK_CalculateSmoothGroups(faces, numFaces, verts, numVerts, points, numPoints, rapi);

	//draw it into the rpgeo context
	for (int i = 0; i < numFaces; i++)
	{
		pskFace_t *face = faces+i;
		pskTriNrm_t *triNrm = triNrms+i;

		char *matName = (face->matIdx >= 0 && face->matIdx < numMats) ? materials[face->matIdx].name : NULL;
		rapi->rpgSetMaterial(matName);

		rapi->rpgBegin(RPGEO_TRIANGLE);
		for (int j = 0; j < 3; j++)
		{
			pskVert_t *vert = verts+face->idx[j];
			rapi->rpgVertUV2f(vert->tc, 0);
			rapi->rpgVertNormal3f(triNrm->nrm[j].v);
			if (wlist)
			{ //convert/feed the weights
				pskWList_t *wv = wlist+vert->pointIdx;
				int *bidx = (int *)rapi->Noesis_UnpooledAlloc(sizeof(int)*wv->numWeights);
				float *bwgt = (float *)rapi->Noesis_UnpooledAlloc(sizeof(float)*wv->numWeights);
				pskWEntry_t *we = wv->weights;
				for (int k = 0; k < wv->numWeights; k++)
				{
					assert(we && we->w);
					bidx[k] = we->w->boneIdx;
					bwgt[k] = we->w->w;
					we = we->next;
				}
				rapi->rpgVertBoneIndexI(bidx, wv->numWeights);
				rapi->rpgVertBoneWeightF(bwgt, wv->numWeights);
				rapi->Noesis_UnpooledFree(bidx);
				rapi->Noesis_UnpooledFree(bwgt);
			}
			rapi->rpgVertex3f(points[vert->pointIdx].v);
		}
		rapi->rpgEnd();
	}

	if (bones && numBones > 0)
	{ //convert and supply bones, if applicable
		modelBone_t *b = Model_PSK_ConvertBones(bones, numBones, rapi);
		if (b)
		{
			rapi->rpgSetExData_Bones(b, numBones);
		}
	}

	rapi->rpgSetTriWinding(true);
	rapi->rpgOptimize();
	noesisModel_t *mdl = rapi->rpgConstructModel();
	if (mdl)
	{
		numMdl = 1; //it's important to set this on success! you can set it to > 1 if you have more than 1 contiguous model in memory
		static float mdlAngOfs[3] = {0.0f, -90.0f, 0.0f};
		rapi->SetPreviewAngOfs(mdlAngOfs); //this'll rotate the model (only in preview mode) into ut-friendly coordinates
	}

	rapi->rpgDestroyContext(pgctx);
	return mdl;
}

//load it (note that you don't need to worry about validation here, if it was done in the Check function)
noesisModel_t *Model_PSA_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	pskBone_t *bones = NULL;
	int numBones = 0;
	psaAnimInfo_t *animInfos = NULL;
	int numAnimInfos = 0;
	psaAnimKey_t *animKeys = NULL;
	int numAnimKeys = 0;

	int ofs = 0;
	while (ofs <= bufferLen-(int)sizeof(pskChunk_t))
	{
		pskChunk_t *chunk = (pskChunk_t *)(fileBuffer+ofs);
		if (!memcmp(chunk->id, "BONENAMES", 9))
		{ //bone data
			bones = (pskBone_t *)(chunk+1);
			numBones = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "ANIMINFO", 8))
		{ //anim sequence data
			animInfos = (psaAnimInfo_t *)(chunk+1);
			numAnimInfos = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "ANIMKEYS", 8))
		{ //anim keyframe data
			animKeys = (psaAnimKey_t *)(chunk+1);
			numAnimKeys = chunk->numRec;
		}
		else if (!memcmp(chunk->id, "SCALEKEYS", 9))
		{ //anim scale data
			//todo - use me
		}
		//else, don't care

		int dataSize = chunk->recSize*chunk->numRec;
		if (dataSize < 0)
		{
			assert(0);
			break;
		}
		ofs += dataSize+sizeof(pskChunk_t);
	}
	if (!bones || numBones <= 0 || !animInfos || numAnimInfos <= 0 ||
		!animKeys || numAnimKeys <= 0)
	{
		rapi->LogOutput("ERROR: PSA did not contain valid animation data.\n");
		return NULL;
	}
	if (numAnimKeys%numBones != 0)
	{
		rapi->LogOutput("ERROR: Number of anim keys must be evenly divisible by the number of bones.\n");
		return NULL;
	}

	modelBone_t *b = Model_PSK_ConvertBones(bones, numBones, rapi);

	//convert anim keys to matrices
	RichMat43 *mats = (RichMat43 *)rapi->Noesis_UnpooledAlloc(sizeof(RichMat43)*numAnimKeys);
	for (int i = 0; i < numAnimKeys; i++)
	{
		psaAnimKey_t *key = animKeys+i;
		RichQuat q = key->rot;
		modelBone_t *bone = b+(i%numBones);
		if (bone->eData.parent)
		{ //flip handedness from ut
			q[0] = -q[0];
			q[1] = -q[1];
			q[2] = -q[2];
		}
		mats[i] = q.ToMat43(true);
		mats[i][3] = key->trans;
	}

	int totalFrames = numAnimKeys/numBones;
	float frameRate = animInfos[0].frameRate;	
	noesisAnim_t *na = rapi->rpgAnimFromBonesAndMatsFinish(b, numBones, (modelMatrix_t *)mats, totalFrames, frameRate);
	rapi->Noesis_UnpooledFree(mats);
	if (na)
	{
		na->aseq = rapi->Noesis_AnimSequencesAlloc(numAnimInfos, totalFrames);
		for (int i = 0; i < numAnimInfos; i++)
		{ //fill in the sequence info
			psaAnimInfo_t *animInfo = animInfos+i;
			noesisASeq_t *seq = na->aseq->s+i;

			seq->name = rapi->Noesis_PooledString(animInfo->name);
			seq->startFrame = animInfo->firstFrame;
			seq->endFrame = animInfo->firstFrame+animInfo->numFrames-1;
			seq->frameRate = animInfo->frameRate;
		}

		numMdl = 1; //this is still important to set for animation output
		static float mdlAngOfs[3] = {0.0f, -90.0f, 0.0f};
		rapi->SetPreviewAngOfs(mdlAngOfs); //this'll rotate the model (only in preview mode) into ut-friendly coordinates
		return rapi->Noesis_AllocModelContainer(NULL, na, 1);
	}
	return NULL;
}

//handle -pskkeepspace
static bool Model_PSK_OptHandlerA(const char *arg, unsigned char *store, int storeSize)
{
	pskOpts_t *lopts = (pskOpts_t *)store;
	assert(storeSize == sizeof(pskOpts_t));
	lopts->keepBoneSpaces = 1;
	return true;
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	int fhPSK = g_nfn->NPAPI_Register("Unreal ActorX Model", ".psk");
	int fhPSA = g_nfn->NPAPI_Register("Unreal ActorX Animation", ".psa");
	if (fhPSK < 0 || fhPSA < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fhPSK, Model_PSK_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fhPSK, Model_PSK_Load);
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fhPSA, Model_PSA_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fhPSA, Model_PSA_Load);
	//export functions
	g_nfn->NPAPI_SetTypeHandler_WriteModel(fhPSK, Model_PSK_Write);
	g_nfn->NPAPI_SetTypeHandler_WriteAnim(fhPSA, Model_PSA_Write);

	//add first parm
	addOptParms_t optParms;
	memset(&optParms, 0, sizeof(optParms));
	optParms.optName = "-pskkeepspace";
	optParms.optDescr = "keep trailing spaces in bone names.";
	optParms.storeSize = sizeof(pskOpts_t);
	optParms.handler = Model_PSK_OptHandlerA;
	g_opts = (pskOpts_t *)g_nfn->NPAPI_AddTypeOption(fhPSK, &optParms);
	assert(g_opts);
	optParms.shareStore = (unsigned char *)g_opts;

	return true;
}

//called by Noesis before the plugin is freed
void NPAPI_ShutdownLocal(void)
{
	//nothing to do in this plugin
}

BOOL APIENTRY DllMain( HMODULE hModule,
                       DWORD  ul_reason_for_call,
                       LPVOID lpReserved
					 )
{
	switch (ul_reason_for_call)
	{
	case DLL_PROCESS_ATTACH:
	case DLL_THREAD_ATTACH:
	case DLL_THREAD_DETACH:
	case DLL_PROCESS_DETACH:
		break;
	}
    return TRUE;
}
