#include "stdafx.h"
#include "ff9types.h"

//is it a model?
bool Model_FF9_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(ff9MdlHdr_t))
	{
		return false;
	}
	ff9MdlHdr_t *hdr = (ff9MdlHdr_t *)fileBuffer;
	if (hdr->meshesOfs <= 0 || hdr->meshesOfs >= bufferLen ||
		hdr->bonesOfs >= bufferLen)
	{
		return false;
	}
	return true;
}

//is it an anim?
bool Model_FF9_CheckAnim(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(ff9AnimHdr_t))
	{
		return false;
	}
	ff9AnimHdr_t *hdr = (ff9AnimHdr_t *)fileBuffer;
	if (hdr->numFrames <= 0 ||// hdr->boneAngHiOfs <= 0 || hdr->boneAngLoOfs <= 0 ||
		hdr->boneAngHiOfs >= bufferLen || hdr->boneAngLoOfs >= bufferLen)
	{
		return false;
	}
	return true;
}

//load anim/skeleton data
static void Model_FF9_LoadAnimData(BYTE *animFile, int animFileSize, ff9MdlBone_t *ff9Bones, int numSrcBones, noesisAnim_t **animOut, modelBone_t **bonesOut,
									   int &numBones, noeRAPI_t *rapi)
{
	numBones = numSrcBones;
	modelBone_t *bones = rapi->Noesis_AllocBones(numBones);

	ff9AnimHdr_t *hdr = (ff9AnimHdr_t *)animFile;

	float *fRootPos = (float *)rapi->Noesis_UnpooledAlloc(sizeof(float)*3*hdr->numFrames);
	for (int fn = 0; fn < hdr->numFrames; fn++)
	{
		float *rp = fRootPos + fn*3;
		for (int j = 0; j < 3; j++)
		{
			if (hdr->rootPosInfo[3] & (1<<j))
			{ //constant value
				rp[j] = (float)hdr->rootPosInfo[j];
			}
			else
			{ //offset
				int ofs = hdr->rootPosInfo[j];
				short *cmpList = (short *)(animFile + ofs);
				rp[j] = (float)cmpList[fn];
			}
		}
	}

	WORD *angLos = (hdr->boneAngLoOfs > 0) ? (WORD *)(animFile+hdr->boneAngLoOfs) : NULL;
	WORD *angHis = (hdr->boneAngHiOfs > 0) ? (WORD *)(animFile+hdr->boneAngHiOfs) : NULL;
	float *fAngs = (float *)rapi->Noesis_UnpooledAlloc(sizeof(float)*3*numBones*hdr->numFrames);
	for (int i = 0; i < numBones; i++)
	{
		WORD *angLo = (angLos) ? angLos + i*4 : NULL;
		WORD *angHi = (angHis) ? angHis + i*4 : NULL;

		const int hiShift = 4;
		for (int fn = 0; fn < hdr->numFrames; fn++)
		{
			short ang[3] = {0, 0, 0};
			for (int j = 0; j < 3; j++)
			{
				if (angHi)
				{
					if (angHi[3] & (1<<j))
					{ //constant value
						ang[j] = ((angHi[j] & 255)<<hiShift);
					}
					else
					{ //offset
						int ofs = angHi[j];
						BYTE *cmpList = animFile+ofs;
						assert(ofs+fn < animFileSize);
						WORD hAng = cmpList[fn];
						ang[j] = (hAng<<hiShift);
					}
				}

				if (angLo)
				{
					if (angLo[3] & (1<<j))
					{ //constant value
						ang[j] |= (angLo[j] & 15);
					}
					else
					{ //offset
						int ofs = angLo[j];
						BYTE *cmpList = animFile+ofs;
						int cidx = fn;
						int crsh = 0;
						if (cidx & 1)
						{
							crsh = 4;
							cidx -= 1;
						}
						cidx /= 2;
						assert(ofs+cidx < animFileSize);
						ang[j] |= ((cmpList[cidx]>>crsh) & 15);
					}
				}
			}


			float *fAng = fAngs + i*hdr->numFrames*3 + fn*3;
			for (int j = 0; j < 3; j++)
			{
				int a = ang[j];
				assert(a <= 4096);
				if (a < 0)
				{
					a += 4096;
				}
				fAng[j] = (float)a / (4096.0f / 360.0f);
			}
		}
	}

	for (int i = 0; i < numBones; i++)
	{
		float *fAng = fAngs + i*hdr->numFrames*3;
		modelBone_t *bone = bones+i;
		ff9MdlBone_t *ff9Bone = ff9Bones+i;

		sprintf_s(bone->name, 32, "bone%02i", i);
		bone->index = i;
		bone->eData.parent = (ff9Bone->parentIdx < numBones && ff9Bone->parentIdx != i) ? bones+ff9Bone->parentIdx : NULL;

		//just take the first frame of animation as the base pose
		bone->mat = g_identityMatrix;
		float ft[3] = {0.0f, 0.0f, (float)ff9Bone->len};
		g_mfn->Math_TranslateMatrix(&bone->mat, ft);
		if (!bone->eData.parent)
		{ //apply root translation
			g_mfn->Math_TranslateMatrix(&bone->mat, fRootPos);
		}
		g_mfn->Math_RotateMatrix(&bone->mat, -fAng[2], 0.0f, 0.0f, 1.0f);
		g_mfn->Math_RotateMatrix(&bone->mat, fAng[1], 0.0f, 1.0f, 0.0f);
		g_mfn->Math_RotateMatrix(&bone->mat, -fAng[0], 1.0f, 0.0f, 0.0f);
	}

	//generate a full animation
	modelMatrix_t *animMats = (modelMatrix_t *)rapi->Noesis_UnpooledAlloc(sizeof(modelMatrix_t)*numBones*hdr->numFrames);
	for (int i = 0; i < numBones; i++)
	{
		ff9MdlBone_t *ff9Bone = ff9Bones+i;
		modelBone_t *bone = bones+i;
		modelMatrix_t *frameMats = animMats + i*hdr->numFrames;
		for (int j = 0; j < hdr->numFrames; j++)
		{
			float *fAng = fAngs + i*hdr->numFrames*3 + j*3;
			modelMatrix_t *mat = animMats + i + j*numBones;

			*mat = g_identityMatrix;
			float ft[3] = {0.0f, 0.0f, (float)ff9Bone->len};
			g_mfn->Math_TranslateMatrix(mat, ft);
			if (!bone->eData.parent)
			{ //apply root translation
				float *rp = fRootPos + j*3;
				g_mfn->Math_TranslateMatrix(mat, rp);
			}
			g_mfn->Math_RotateMatrix(mat, -fAng[2], 0.0f, 0.0f, 1.0f);
			g_mfn->Math_RotateMatrix(mat, fAng[1], 0.0f, 1.0f, 0.0f);
			g_mfn->Math_RotateMatrix(mat, -fAng[0], 1.0f, 0.0f, 0.0f);
		}
	}

	rapi->rpgMultiplyBones(bones, numBones);

	*animOut = rapi->rpgAnimFromBonesAndMats(bones, numBones, animMats, hdr->numFrames, 15.0f);

	rapi->Noesis_UnpooledFree(animMats);
	rapi->Noesis_UnpooledFree(fAngs);
	rapi->Noesis_UnpooledFree(fRootPos);
	*bonesOut = bones;
}

//load corresponding anim
static void Model_FF9_LoadAnimForBones(ff9MdlBone_t *ff9Bones, int numSrcBones, noesisAnim_t **animOut, modelBone_t **bonesOut, int &numBones, noeRAPI_t *rapi)
{
	int animFileSize = 0;
	BYTE *animFile = rapi->Noesis_LoadPairedFile("FF9 Anim", "ff9anm", animFileSize, NULL);
	if (!animFile)
	{ //then maybe there's one in the folder
		wchar_t tmp[MAX_NOESIS_PATH];
		rapi->Noesis_GetDirForFilePathW(tmp, rapi->Noesis_GetInputNameW());
		wcscat_s(tmp, MAX_NOESIS_PATH, L"dbfile0001.ff9anm");
		animFile = rapi->Noesis_ReadFileW(tmp, &animFileSize);
		if (!animFile)
		{
			return;
		}
	}

	Model_FF9_LoadAnimData(animFile, animFileSize, ff9Bones, numSrcBones, animOut, bonesOut, numBones, rapi);
	rapi->Noesis_UnpooledFree(animFile);
}

//todo - use external texture page data
static int Model_FF9_SetMaterial(int idx, noeRAPI_t *rapi, CArrayList<noesisTex_t *> &texList)
{
	char matName[64];
	sprintf_s(matName, 64, "dbfile%04i", idx); //total hack
	rapi->rpgSetMaterial(matName);

	return idx;
}

//transform vert with bone matrix
static void Model_FF9_TransformVert(modelBone_t *bones, int numBones, ff9MdlVert_t *vert, float *dst, noeRAPI_t *rapi)
{
	if (bones && vert->boneIdx < numBones)
	{
		float t[3];
		t[0] = (float)vert->pos[0];
		t[1] = (float)vert->pos[1];
		t[2] = (float)vert->pos[2];
		g_mfn->Math_TransformPointByMatrix(&bones[vert->boneIdx].mat, t, dst);
		float w = 1.0f;
		int idx = vert->boneIdx;
		rapi->rpgVertBoneIndexI(&idx, 1);
		rapi->rpgVertBoneWeightF(&w, 1);
	}
	else
	{
		dst[0] = (float)vert->pos[0];
		dst[1] = (float)vert->pos[1];
		dst[2] = (float)vert->pos[2];
	}
}

//scale uv
static void Model_FF9_DecodeUV(ff9MdlUV_t *uv, float *dst, int curTex, CArrayList<noesisTex_t *> &texList)
{
	float divW = 128.0f;
	float divH = 128.0f;
	if (curTex >= 0 && curTex < texList.Num())
	{
		noesisTex_t *tex = texList[curTex];
		assert(tex);
		divW = (float)tex->w;
		divH = (float)tex->h;
	}
	dst[0] = (float)uv->uv[0] / divW;
	dst[1] = (float)uv->uv[1] / divH;
}

//called by both model and anim load routines
static noesisModel_t *Model_FF9_LoadEx(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi,
									   noesisAnim_t *anim, modelBone_t *bones, int numBones)
{
	void *pgctx = rapi->rpgCreateContext();
	ff9MdlHdr_t *hdr = (ff9MdlHdr_t *)fileBuffer;
	ff9MdlBone_t *ff9Bones = (hdr->numBones > 0 && hdr->bonesOfs > 0) ? (ff9MdlBone_t *)(fileBuffer+hdr->bonesOfs) : NULL;
	ff9MdlMesh_t *meshes = (ff9MdlMesh_t *)(fileBuffer+hdr->meshesOfs);

	CArrayList<noesisTex_t *> texList;
	CArrayList<noesisMaterial_t *> matList;

	bool (*loadTM1Fn)(BYTE *fileBuffer, int bufferLen, CArrayList<noesisTex_t *> &noeTex, noeRAPI_t *rapi);
	*((NOEXFUNCTION *)&loadTM1Fn) = rapi->Noesis_GetExtProc("Image_LoadTIM1");
	if (loadTM1Fn)
	{ //hack, try loading some TIMs for the model
		const int maxLoadTims = 256;
		wchar_t baseTimPath[MAX_NOESIS_PATH];
		rapi->Noesis_GetDirForFilePathW(baseTimPath, rapi->Noesis_GetInputNameW());
		for (int i = 0; i < maxLoadTims; i++)
		{
			wchar_t timPath[MAX_NOESIS_PATH];
			swprintf(timPath, L"%sdbfile%04i.tim", baseTimPath, i);
			BYTE *timFile;
			int timFileLen;
			timFile = rapi->Noesis_ReadFileW(timPath, &timFileLen);
			if (!timFile)
			{ //try a hardcoded folder name hack (assumes this is data this plugin extracted)
				swprintf(timPath, L"%s..\\dbfile0001_files\\dbfile%04i.tim", baseTimPath, i);
				timFile = rapi->Noesis_ReadFileW(timPath, &timFileLen);
			}
			if (timFile)
			{ //load it
				int n = texList.Num();
				loadTM1Fn(timFile, timFileLen, texList, rapi);
				rapi->Noesis_UnpooledFree(timFile);
				for (int j = n; j < texList.Num(); j++)
				{ //add materials for each texture
					noesisTex_t *tex = texList[j];
					assert(tex);
					noesisMaterial_t *mat = rapi->Noesis_GetMaterialList(1, false);
					mat->texIdx = j;
					char matName[64];
					sprintf(matName, "dbfile%04i", i);
					mat->name = rapi->Noesis_PooledString(matName);
					tex->filename = rapi->Noesis_PooledString(matName);
					matList.Append(mat);
				}
			}
			else
			{ //stop trying at the first failure
				break;
			}
		}
	}

	const int quadMap[6] = {2, 1, 0, 1, 2, 3};
	int curTex = -1;
	for (int i = 0; i < hdr->numMeshes; i++)
	{
		ff9MdlMesh_t *mesh = meshes+i;
		if (mesh->vertDataOfs <= 0 || mesh->uvDataOfs <= 0 || mesh->polyDataOfs <= 0)
		{
			continue;
		}
		ff9MdlVert_t *verts = (ff9MdlVert_t *)(fileBuffer+mesh->vertDataOfs);
		ff9MdlUV_t *uvs = (ff9MdlUV_t *)(fileBuffer+mesh->uvDataOfs);
		BYTE *polyData = fileBuffer+mesh->polyDataOfs;
		if (mesh->numQuadsA > 0)
		{
			ff9MdlQuadA_t *quads = (ff9MdlQuadA_t *)polyData;
			for (int j = 0; j < mesh->numQuadsA; j++)
			{
				ff9MdlQuadA_t *quad = quads+j;
				curTex = Model_FF9_SetMaterial(quad->texIdx, rapi, texList);
				rapi->rpgBegin(RPGEO_TRIANGLE);
				for (int k = 0; k < 6; k++)
				{
					const int idx = quadMap[k];
					float pos[3];
					Model_FF9_TransformVert(bones, numBones, verts+quad->vIdx[idx], pos, rapi);
					float uv[2];
					Model_FF9_DecodeUV(uvs+quad->uvIdx[idx], uv, curTex, texList);
					rapi->rpgVertUV2f(uv, 0);
					rapi->rpgVertex3f(pos);
				}
				rapi->rpgEnd();
			}
			polyData += sizeof(ff9MdlQuadA_t)*mesh->numQuadsA;
		}
		if (mesh->numTrisA > 0)
		{
			ff9MdlTriA_t *tris = (ff9MdlTriA_t *)polyData;
			for (int j = 0; j < mesh->numTrisA; j++)
			{
				ff9MdlTriA_t *tri = tris+j;
				curTex = Model_FF9_SetMaterial(tri->texIdx, rapi, texList);
				rapi->rpgBegin(RPGEO_TRIANGLE);
				for (int k = 0; k < 3; k++)
				{
					int idx = 2-k;
					float pos[3];
					Model_FF9_TransformVert(bones, numBones, verts+tri->vIdx[idx], pos, rapi);
					float uv[2];
					Model_FF9_DecodeUV(uvs+tri->uvIdx[idx], uv, curTex, texList);

					rapi->rpgVertUV2f(uv, 0);
					rapi->rpgVertex3f(pos);
				}
				rapi->rpgEnd();
			}
			polyData += sizeof(ff9MdlTriA_t)*mesh->numTrisA;
		}

		//todo - handle b and c types here
	}

	rapi->rpgSetExData_Anims(anim);
	rapi->rpgSetExData_Bones(bones, numBones);

	if (texList.Num() > 0)
	{
		noesisMatData_t *md = rapi->Noesis_GetMatDataFromLists(matList, texList);
		rapi->rpgSetExData_Materials(md);
	}

	rapi->rpgOptimize();
	noesisModel_t *mdl = rapi->rpgConstructModel();
	if (mdl)
	{
		numMdl = 1; //it's important to set this on success! you can set it to > 1 if you have more than 1 contiguous model in memory
		float mdlAngOfs[3] = {0.0f, 270.0f, 270.0f};
		rapi->SetPreviewAngOfs(mdlAngOfs);
		if (anim)
		{
			rapi->SetPreviewAnimSpeed(15.0f);
			rapi->SetPreviewOption("setAnimPlay", "1");
		}
	}

	rapi->rpgDestroyContext(pgctx);
	return mdl;
}

//load the model
noesisModel_t *Model_FF9_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	ff9MdlHdr_t *hdr = (ff9MdlHdr_t *)fileBuffer;
	ff9MdlBone_t *ff9Bones = (hdr->numBones > 0 && hdr->bonesOfs > 0) ? (ff9MdlBone_t *)(fileBuffer+hdr->bonesOfs) : NULL;
	noesisAnim_t *anim = NULL;
	modelBone_t *bones = NULL;
	int numBones = 0;
	if (ff9Bones)
	{
		Model_FF9_LoadAnimForBones(ff9Bones, hdr->numBones, &anim, &bones, numBones, rapi);
	}

	return Model_FF9_LoadEx(fileBuffer, bufferLen, numMdl, rapi, anim, bones, numBones);
}

//load anim
noesisModel_t *Model_FF9_LoadAnim(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	int mdlFileSize = 0;
	wchar_t tmp[MAX_NOESIS_PATH];
	rapi->Noesis_GetDirForFilePathW(tmp, rapi->Noesis_GetInputNameW());
	wcscat_s(tmp, MAX_NOESIS_PATH, L"dbfile0000.ff9mdl");
	BYTE *mdlFile = rapi->Noesis_ReadFileW(tmp, &mdlFileSize);
	if (!mdlFile)
	{ //then prompt for one
		mdlFile = rapi->Noesis_LoadPairedFile("FF9 Model", ".ff9mdl", mdlFileSize, NULL);
		if (!mdlFile)
		{ //anim data is useless without model data
			return NULL;
		}
	}

	ff9MdlHdr_t *mdlHdr = (ff9MdlHdr_t *)mdlFile;
	ff9MdlBone_t *ff9Bones = (mdlHdr->numBones > 0 && mdlHdr->bonesOfs > 0) ? (ff9MdlBone_t *)(mdlFile+mdlHdr->bonesOfs) : NULL;
	if (!ff9Bones)
	{ //user didn't select a model with a skeleton
		rapi->Noesis_UnpooledFree(mdlFile);
		return NULL;
	}

	noesisAnim_t *anim = NULL;
	modelBone_t *bones = NULL;
	int numBones = 0;
	Model_FF9_LoadAnimData(fileBuffer, bufferLen, ff9Bones, mdlHdr->numBones, &anim, &bones, numBones, rapi);
	noesisModel_t *mdl = Model_FF9_LoadEx(mdlFile, mdlFileSize, numMdl, rapi, anim, bones, numBones);

	rapi->Noesis_UnpooledFree(mdlFile);
	return mdl;
}
