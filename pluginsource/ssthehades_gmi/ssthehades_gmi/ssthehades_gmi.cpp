//Saint Seiya: The Hades (PS2) import plugin
//thanks to fatduck for the file layout, and qslash for additional contributions

#include "stdafx.h"

const char *g_pPluginName = "ssthehades_gmi";
const char *g_pPluginDesc = "GMI format handler, by Dick.";

typedef struct gmiHdr_s
{
	int				id; //0x20040319
	int				size;
	int				unkOfsA;
	int				unkB;
	WORD			numBones;
	WORD			numMeshes;
	int				ofsBones;
	int				ofsMeshes;
	int				unkC;
	int				unkD;
} gmiHdr_t;

typedef struct gmiMesh_s
{
	WORD			unkA;
	int				numVerts;
	int				numUnkB;
	short			matIdx;
	int				ofsPos;
	int				ofsNrm;
	int				ofsClr;
	int				ofsUV;
	int				ofsBoneIdx;
	int				ofsBoneWgt;
	BYTE			boneList[12];
} gmiMesh_t;

typedef struct gmiBone_s
{
	RichMat44		mat;
	short			parentIdx;
	short			unkA;
	short			unkB;
	char			name[42];
} gmiBone_t;

typedef struct gmiIntrVert_s
{
	RichVec3		pos;
	RichVec3		nrm;
	float			clr[4];
	float			uv[2];
	int				bi[4];
	float			bw[4];
} gmiIntrVert_t;

typedef struct gmiCmpHdr_s
{
	BYTE			id[4]; //"CMPS"
	int				cmpType;
	int				decompSize;
	int				resv;
} gmiCmpHdr_t;

typedef struct tplHdr_s
{
	BYTE			id[4]; //"FJF\0"
	int				numImages:24;
	int				unk:8;
	//offsets follow, then...global image indices? (indices aren't always there, though)
} tplHdr_t;

typedef struct itaJobEntry_s
{
	BYTE			*data;
	int				size;
} itaJobEntry_t;

//decompress data
static BYTE *Model_GMI_Decompress(BYTE *src, int &len, noeRAPI_t *rapi)
{
	gmiCmpHdr_t *cmpHdr = (gmiCmpHdr_t *)src;
	int srcLen = len;
	int dstLen = cmpHdr->decompSize;
	BYTE *dst = (BYTE *)rapi->Noesis_PooledAlloc(dstLen);
	int srcPtr = sizeof(gmiCmpHdr_t);
	int dstPtr = 0;

	while (srcPtr < srcLen && dstPtr < dstLen)
	{
		BYTE ctrl = src[srcPtr++];
		for (int i = 0; i < 8 && srcPtr < srcLen && dstPtr < dstLen; i++)
		{
			if (ctrl & (1<<i))
			{ //literal
				dst[dstPtr++] = src[srcPtr++];
			}
			else
			{ //ofs+len
				WORD ol = *(WORD *)(src+srcPtr);
				srcPtr += sizeof(WORD);
				int len = 3 + ((ol>>8) & 15);
				int relOfs = (ol & 255) | ((ol>>12) << 8);
				int ofs = dstPtr - ((dstPtr-18-relOfs) & 4095);
				for (int j = 0; j < len && dstPtr < dstLen; j++)
				{
					if (ofs+j < 0 || ofs+j >= dstPtr)
					{
						dst[dstPtr++] = 0;
					}
					else
					{
						dst[dstPtr++] = dst[ofs+j];
					}
				}
			}
		}
	}
	assert(srcPtr <= srcLen);
	assert(dstPtr <= dstLen);

	len = dstLen;
	return dst;
}

//see if something is valid tpl data
bool Model_TPL_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen >= sizeof(gmiCmpHdr_t))
	{
		gmiCmpHdr_t *cmpHdr = (gmiCmpHdr_t *)fileBuffer;
		if (!memcmp(cmpHdr->id, "CMPS", 4) && cmpHdr->cmpType == 1)
		{
			return true;
		}
	}
	if (bufferLen < sizeof(tplHdr_t))
	{
		return false;
	}
	tplHdr_t *hdr = (tplHdr_t *)fileBuffer;
	if (memcmp(hdr->id, "FJF\0", 4))
	{
		return false;
	}
	if (hdr->numImages <= 0)
	{
		return false;
	}
	int eofs = sizeof(tplHdr_t) + hdr->numImages*sizeof(int);
	if (eofs <= 0 || eofs > bufferLen)
	{
		return false;
	}

	if (!rapi->Noesis_GetExtProc("Image_LoadTIM2"))
	{ //this isn't a version of Noesis that supports the Image_LoadTIM2 extension
		return false;
	}

	return true;
}

//load textures from tpl
static void Model_TPL_GetTexList(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi,
								 CArrayList<noesisTex_t *> &texList, CArrayList<noesisMaterial_t *> &matList)
{
	gmiCmpHdr_t *cmpHdr = (gmiCmpHdr_t *)fileBuffer;
	if (!memcmp(cmpHdr->id, "CMPS", 4) && cmpHdr->cmpType == 1)
	{ //try to decompress it
		fileBuffer = Model_GMI_Decompress(fileBuffer, bufferLen, rapi);
		if (!Model_TPL_Check(fileBuffer, bufferLen, rapi))
		{
			rapi->LogOutput("ERROR: Compressed file did not contain an actual TPL set.\n");
			return;
		}
	}

	bool (*loadTM2Fn)(BYTE *fileBuffer, int bufferLen, CArrayList<noesisTex_t *> &noeTex, noeRAPI_t *rapi, bool untwiddlePixels);
	*((NOEXFUNCTION *)&loadTM2Fn) = rapi->Noesis_GetExtProc("Image_LoadTIM2");
	assert(loadTM2Fn);

	tplHdr_t *hdr = (tplHdr_t *)fileBuffer;
	int *imgOfs = (int *)(hdr+1);

	for (int i = 0; i < hdr->numImages; i++)
	{
		BYTE *imgData = fileBuffer + imgOfs[i];
		if (memcmp(imgData, "TIM2", 4) && memcmp(imgData, "TIM3", 4))
		{
			continue;
		}
		int imgSize = (i < hdr->numImages-1) ? imgOfs[i+1]-imgOfs[i] : bufferLen-imgOfs[i];
		noesisMaterial_t *mat = rapi->Noesis_GetMaterialList(1, true);
		char matName[64];
		sprintf(matName, "tpltex%02i", i);
		mat->name = rapi->Noesis_PooledString(matName);
		mat->noDefaultBlend = true;
		if (loadTM2Fn(imgData, imgSize, texList, rapi, false))
		{
			noesisTex_t *t = texList[texList.Num()-1];
			assert(t);
			assert(t->type == NOESISTEX_RGBA32);
			for (int j = 0; j < t->w*t->h; j++)
			{
				BYTE *p = t->data + j*4;
				p[3] = (BYTE)g_mfn->Math_Min2(255.0f, (float)p[3] * 2.0f);
			}

			mat->texIdx = texList.Num()-1;
			t->filename = mat->name;
		}
		matList.Append(mat);
	}
}

//load tpl
noesisModel_t *Model_TPL_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	CArrayList<noesisTex_t *> texList;
	CArrayList<noesisMaterial_t *> matList;
	Model_TPL_GetTexList(fileBuffer, bufferLen, rapi, texList, matList);

	if (texList.Num() > 0)
	{
		noesisMatData_t *md = rapi->Noesis_GetMatDataFromLists(matList, texList);
		numMdl = 1;
		return rapi->Noesis_AllocModelContainer(md, NULL, 0);
	}

	return NULL;
}

//see if something is valid gmi data
bool Model_GMI_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen >= sizeof(gmiCmpHdr_t))
	{
		gmiCmpHdr_t *cmpHdr = (gmiCmpHdr_t *)fileBuffer;
		if (!memcmp(cmpHdr->id, "CMPS", 4) && cmpHdr->cmpType == 1)
		{
			return true;
		}
	}
	if (bufferLen < sizeof(gmiHdr_t))
	{
		return false;
	}
	gmiHdr_t *hdr = (gmiHdr_t *)fileBuffer;
	if (hdr->id != 0x20040319 && hdr->id != 0x20030818) //0x20030818 is itadaki st
	{
		return false;
	}
	if (hdr->numMeshes <= 0 || hdr->ofsMeshes <= 0 || hdr->ofsMeshes >= bufferLen)
	{
		return false;
	}
	return true;
}

//called by gmi loader and job loader
noesisModel_t *Model_GMI_LoadEx(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi,
							  CArrayList<noesisTex_t *> &texList, CArrayList<noesisMaterial_t *> &matList)
{
	gmiHdr_t *hdr = (gmiHdr_t *)fileBuffer;
	gmiBone_t *srcBones = (hdr->numBones > 0 && hdr->ofsBones > 0) ? (gmiBone_t *)(fileBuffer+hdr->ofsBones) : NULL;
	modelBone_t *bones = NULL;
	int numBones = 0;
	if (srcBones)
	{ //convert bones
		numBones = hdr->numBones;
		bones = rapi->Noesis_AllocBones(numBones);
		for (int i = 0; i < numBones; i++)
		{
			gmiBone_t *srcBone = srcBones+i;
			modelBone_t *dstBone = bones+i;

			dstBone->mat = srcBone->mat.ToMat43().m;
			dstBone->index = i;
			dstBone->eData.parent = (srcBone->parentIdx >= 0) ? bones+srcBone->parentIdx : NULL;
			memcpy(dstBone->name, srcBone->name, sizeof(dstBone->name)-1);
			dstBone->name[sizeof(dstBone->name)-1] = 0;
		}
		rapi->rpgMultiplyBones(bones, numBones);
	}

	void *pgctx = rapi->rpgCreateContext();

	CArrayList<gmiIntrVert_t> verts;

	bool isIta = (hdr->id == 0x20030818);

	gmiMesh_t *meshes = (gmiMesh_t *)(fileBuffer + hdr->ofsMeshes);
	for (int i = 0; i < hdr->numMeshes; i++)
	{
		gmiMesh_t *mesh = meshes+i;
		if (mesh->numVerts <= 0 || mesh->ofsPos <= 0 || mesh->ofsPos >= bufferLen)
		{
			continue;
		}

		char meshName[64];
		sprintf(meshName, "mesh%02i", i);
		rapi->rpgSetName(meshName);
		noesisTex_t *tex = NULL;
		if (mesh->matIdx >= 0)
		{
			char matName[64];
			sprintf(matName, "tpltex%02i", mesh->matIdx);
			rapi->rpgSetMaterial(matName);
			if (mesh->matIdx < texList.Num())
			{
				tex = texList[mesh->matIdx];
			}
		}
		else
		{
			rapi->rpgSetMaterial(NULL);
		}

		float *posAr = (float *)(fileBuffer + mesh->ofsPos);
		short *nrmAr = (mesh->ofsNrm > 0 && mesh->ofsNrm < bufferLen) ? (short *)(fileBuffer + mesh->ofsNrm) : NULL;
		BYTE *clrAr = (mesh->ofsClr > 0 && mesh->ofsClr < bufferLen) ? (BYTE *)(fileBuffer + mesh->ofsClr) : NULL;
		float *uvAr = (mesh->ofsUV > 0 && mesh->ofsUV < bufferLen) ? (float *)(fileBuffer + mesh->ofsUV) : NULL;
		BYTE *bidxAr = (mesh->ofsBoneIdx > 0 && mesh->ofsBoneIdx < bufferLen) ? (BYTE *)(fileBuffer + mesh->ofsBoneIdx) : NULL;
		float *bwgtAr = (mesh->ofsBoneWgt > 0 && mesh->ofsBoneWgt < bufferLen) ? (float *)(fileBuffer + mesh->ofsBoneWgt) : NULL;

		int lastDrawIdx = 0;
		int ntris = 0;
		int numVerts = (mesh->numVerts & 32767);
		for (int j = 0; j < numVerts; j++)
		{
			gmiIntrVert_t vert;
			memset(&vert, 0, sizeof(vert));

			float *pos = posAr + j*4;
			RichVec3 &vpos = *((RichVec3 *)pos);

			if (uvAr)
			{
				float xfac = (tex) ? (float)tex->w / (float)g_mfn->Math_NextPow2(tex->w) : 1.0f;
				float yfac = (tex) ? (float)tex->h / (float)g_mfn->Math_NextPow2(tex->h) : 1.0f;

				float *uv = uvAr + j*2;
				vert.uv[0] = uv[0] / xfac;
				if (isIta)
				{
					vert.uv[1] = -uv[1] / yfac;
				}
				else
				{
					vert.uv[1] = uv[1] / yfac;
				}
			}

			if (clrAr)
			{
				if (isIta)
				{
					float *clr = (float *)(clrAr + j*16);
					vert.clr[0] = clr[0];
					vert.clr[1] = clr[1];
					vert.clr[2] = clr[2];
					vert.clr[3] = 1.0f-clr[3];
				}
				else
				{
					BYTE *clr = clrAr + j*4;
					vert.clr[0] = (float)clr[0] / 255.0f;
					vert.clr[1] = (float)clr[1] / 255.0f;
					vert.clr[2] = (float)clr[2] / 255.0f;
					vert.clr[3] = (float)clr[3] / 127.0f;
				}
				assert(vert.clr[0] <= 1.0f);
				assert(vert.clr[1] <= 1.0f);
				assert(vert.clr[2] <= 1.0f);
				assert(vert.clr[3] <= 1.0f);
			}

			if (nrmAr)
			{
				if (isIta)
				{
					float *fnrm = (float *)(nrmAr + j*8);
					vert.nrm[0] = (float)fnrm[0] / (float)fnrm[3];
					vert.nrm[1] = (float)fnrm[1] / (float)fnrm[3];
					vert.nrm[2] = (float)fnrm[2] / (float)fnrm[3];
					vert.nrm.Normalize();
				}
				else
				{
					short *snrm = nrmAr + j*4;
					vert.nrm[0] = (float)snrm[0] / (float)snrm[3];
					vert.nrm[1] = (float)snrm[1] / (float)snrm[3];
					vert.nrm[2] = (float)snrm[2] / (float)snrm[3];
					vert.nrm.Normalize();
				}
			}

			if (bidxAr && bones && numBones > 0)
			{
				int wFlNum = (isIta) ? 4 : 2;
				BYTE *bidx = bidxAr + j*4;
				float *bwgt = (bwgtAr) ? bwgtAr + j*wFlNum : NULL;
				int numWeights;
				if (isIta)
				{
					numWeights = 4;
				}
				else if (bwgt)
				{
					numWeights = 2;
				}
				else
				{
					numWeights = 1;
				}

				int bidxList[4] = {-1, -1, -1, -1};
				for (int k = 0; k < numWeights; k++)
				{
					int useIdx = k;
					if (bidx[useIdx] == 255)
					{
						continue;
					}
					if (isIta)
					{
						bidxList[k] = bidx[useIdx];
					}
					else
					{
						assert(bidx[useIdx] < 12);
						bidxList[k] = mesh->boneList[bidx[useIdx]];
					}
					assert(bidxList[k] < numBones);
					vert.bi[k] = bidxList[k];
					vert.bw[k] = (bwgt) ? bwgt[k] : 1.0f;
				}

				assert(bidxList[0] >= 0);
				if (bidxList[1] < 0)
				{ //only 1 weight actually used
					RichMat43 *bmat = (RichMat43 *)&bones[bidxList[0]].mat;
					vert.pos = bmat->TransformPoint(vpos);
					vert.nrm = bmat->TransformNormal(vert.nrm);
				}
				else
				{ //both weights are used - already in base position
					vert.pos = vpos;
				}
				vert.nrm.Normalize();
			}
			else
			{
				vert.pos = vpos;
			}

			verts.Append(vert);

			if (pos[3] == 1.0f)
			{ //draw strip
				assert(lastDrawIdx <= verts.Num());
				rpgeoPrimType_e prim = RPGEO_TRIANGLE_STRIP_FLIPPED;
				int vnum = (verts.Num() - lastDrawIdx);
				if (vnum < 3)
				{ //need at least 3 verts to start a strip
					lastDrawIdx -= (3-vnum);
					assert(lastDrawIdx >= 0);
					vnum = 3;
				}

				if (ntris & 1)
				{
					prim = RPGEO_TRIANGLE_STRIP;
				}
				ntris += 1 + (vnum-3);

				gmiIntrVert_t *startVert = &verts[lastDrawIdx];
				if (bidxAr)
				{
					rapi->rpgBindBoneIndexBuffer(startVert->bi, RPGEODATA_INT, sizeof(gmiIntrVert_t), 4);
					rapi->rpgBindBoneWeightBuffer(startVert->bw, RPGEODATA_FLOAT, sizeof(gmiIntrVert_t), 4);					
				}
				rapi->rpgBindUV1Buffer(startVert->uv, RPGEODATA_FLOAT, sizeof(gmiIntrVert_t));
				if (clrAr)
				{
					rapi->rpgBindColorBuffer(startVert->clr, RPGEODATA_FLOAT, sizeof(gmiIntrVert_t), 4);
				}
				if (nrmAr)
				{
					rapi->rpgBindNormalBuffer(startVert->nrm.v, RPGEODATA_FLOAT, sizeof(gmiIntrVert_t));
				}
				rapi->rpgBindPositionBuffer(startVert->pos.v, RPGEODATA_FLOAT, sizeof(gmiIntrVert_t));

				rapi->rpgCommitTriangles(NULL, RPGEODATA_INT, vnum, prim, true);
				rapi->rpgClearBufferBinds();

				lastDrawIdx = verts.Num()+1;
			}
		}
		assert(lastDrawIdx == verts.Num()+1);
		verts.Reset();
	}

	if (texList.Num() > 0)
	{
		noesisMatData_t *md = rapi->Noesis_GetMatDataFromLists(matList, texList);
		rapi->rpgSetExData_Materials(md);
	}

	rapi->rpgSetExData_Bones(bones, numBones);
	noesisModel_t *mdl = rapi->rpgConstructModel();
	if (mdl)
	{
		numMdl = 1; //it's important to set this on success! you can set it to > 1 if you have more than 1 contiguous model in memory
		float mdlAngOfs[3] = {0.0f, 90.0f, 270.0f};
		rapi->SetPreviewAngOfs(mdlAngOfs);
		rapi->SetPreviewOption("noTextureLoad", "1");
	}
	rapi->rpgDestroyContext(pgctx);
	return mdl;
}

//load it (note that you don't need to worry about validation here, if it was done in the Check function)
noesisModel_t *Model_GMI_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	gmiCmpHdr_t *cmpHdr = (gmiCmpHdr_t *)fileBuffer;
	if (!memcmp(cmpHdr->id, "CMPS", 4) && cmpHdr->cmpType == 1)
	{ //try to decompress it
		fileBuffer = Model_GMI_Decompress(fileBuffer, bufferLen, rapi);
		if (!Model_GMI_Check(fileBuffer, bufferLen, rapi))
		{
			rapi->LogOutput("ERROR: Compressed file did not contain an actual GMI model.\n");
			return NULL;
		}
	}

	gmiHdr_t *hdr = (gmiHdr_t *)fileBuffer;

	CArrayList<noesisTex_t *> texList;
	CArrayList<noesisMaterial_t *> matList;

	//try to get some textures
	if (hdr->numBones > 0)
	{ //but, hack, don't try if it's not a boned model
		wchar_t tplFileName[MAX_NOESIS_PATH];
		rapi->Noesis_GetExtensionlessNameW(tplFileName, rapi->Noesis_GetInputNameW());
		wcscat(tplFileName, L".tpl");
		int tplSize = 0;
		BYTE *tplFile = rapi->Noesis_ReadFileW(tplFileName, &tplSize);
		if (!tplFile)
		{
			tplFile = rapi->Noesis_LoadPairedFile("TPL Texture Package", ".tpl", tplSize, NULL);
		}
		if (tplFile)
		{
			Model_TPL_GetTexList(tplFile, tplSize, rapi, texList, matList);
			rapi->Noesis_UnpooledFree(tplFile);
		}
	}

	return Model_GMI_LoadEx(fileBuffer, bufferLen, numMdl, rapi, texList, matList);
}

//see if something is valid job data
bool Model_JOB_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(tplHdr_t))
	{
		return false;
	}
	tplHdr_t *hdr = (tplHdr_t *)fileBuffer;
	if (memcmp(hdr->id, "FJF\0", 4))
	{
		return false;
	}
	if (hdr->numImages <= 0)
	{
		return false;
	}
	int eofs = sizeof(tplHdr_t) + hdr->numImages*sizeof(int);
	if (eofs <= 0 || eofs > bufferLen)
	{
		return false;
	}

	if (!rapi->Noesis_GetExtProc("Image_LoadTIM2"))
	{ //this isn't a version of Noesis that supports the Image_LoadTIM2 extension
		return false;
	}

	return true;
}

//load job
noesisModel_t *Model_JOB_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	tplHdr_t *hdr = (tplHdr_t *)fileBuffer;
	int *fileOfs = (int *)(hdr+1);

	CArrayList<itaJobEntry_t> imgEntries;
	CArrayList<itaJobEntry_t> mdlEntries;

	CArrayList<noesisTex_t *> texList;
	CArrayList<noesisMaterial_t *> matList;

	for (int i = 0; i < hdr->numImages; i++)
	{
		assert(fileOfs[i] < bufferLen);
		BYTE *fileData = fileBuffer + fileOfs[i];
		int fileSize = (i < hdr->numImages-1) ? fileOfs[i+1]-fileOfs[i] : bufferLen-fileOfs[i];
		itaJobEntry_t e;
		memset(&e, 0, sizeof(e));
		e.data = fileData;
		e.size = fileSize;
		if (Model_TPL_Check(fileData, fileSize, rapi))
		{
			imgEntries.Append(e);
		}
		else if (Model_GMI_Check(fileData, fileSize, rapi))
		{
			mdlEntries.Append(e);
		}
		else
		{
			rapi->LogOutput("Did not handle file %i.\n", i);
		}
	}

	for (int i = 0; i < imgEntries.Num(); i++)
	{
		itaJobEntry_t &e = imgEntries[i];
		Model_TPL_GetTexList(e.data, e.size, rapi, texList, matList);
	}
	for (int i = 0; i < matList.Num(); i++)
	{ //don't turn default blend and face culling off for this one
		matList[i]->noDefaultBlend = false;
		matList[i]->flags |= NMATFLAG_TWOSIDED;
	}

	CArrayList<noesisModel_t *> models;
	for (int i = 0; i < mdlEntries.Num(); i++)
	{
		itaJobEntry_t &e = mdlEntries[i];
		int nmdl = 0;
		noesisModel_t *mdl = Model_GMI_LoadEx(e.data, e.size, nmdl, rapi, texList, matList);
		if (mdl)
		{
			models.Append(mdl);
		}
	}

	if (models.Num() <= 0)
	{
		if (texList.Num() > 0)
		{
			noesisMatData_t *md = rapi->Noesis_GetMatDataFromLists(matList, texList);
			numMdl = 1;
			return rapi->Noesis_AllocModelContainer(md, NULL, 0);
		}
		return NULL;
	}

	noesisModel_t *mdls = rapi->Noesis_ModelsFromList(models, numMdl);
	return mdls;
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	if (g_nfn->NPAPI_GetAPIVersion() < NOESIS_PLUGINAPI_VERSION)
	{ //don't run on any version of noesis that isn't the latest one as of this compile
		return false;
	}

	int fh;
	//models
	fh = g_nfn->NPAPI_Register("Saint Seiya: The Hades GMI Model", ".gmi");
	if (fh < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fh, Model_GMI_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fh, Model_GMI_Load);

	//image containers
	fh = g_nfn->NPAPI_Register("Saint Seiya: The Hades TPL Images", ".tpl");
	if (fh < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fh, Model_TPL_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fh, Model_TPL_Load);

	//model+image containers
	fh = g_nfn->NPAPI_Register("DQ&FF in Itadaki Street Special JOB", ".job");
	if (fh < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fh, Model_JOB_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fh, Model_JOB_Load);

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
    return TRUE;
}
