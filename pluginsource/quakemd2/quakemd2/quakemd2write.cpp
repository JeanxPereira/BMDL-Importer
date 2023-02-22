//i'm writing this while completely drunk. apologies for any errors!

#include "stdafx.h"
#include "quakemd2.h"

typedef struct md2AnimHold_s
{
	modelMatrix_t		*mats;
	int					numFrames;
	float				frameRate;
	int					numBones;
} md2AnimHold_t;

//retrives animation data
static md2AnimHold_t *Model_MD2_GetAnimData(noeRAPI_t *rapi)
{
	int animDataSize;
	BYTE *animData = rapi->Noesis_GetExtraAnimData(animDataSize);
	if (!animData)
	{
		return NULL;
	}

	noesisAnim_t *anim = rapi->Noesis_AnimAlloc("animout", animData, animDataSize); //animation containers are pool-allocated, so don't worry about freeing them
	//copy off the raw matrices for the animation frames
	md2AnimHold_t *amd2 = (md2AnimHold_t *)rapi->Noesis_PooledAlloc(sizeof(md2AnimHold_t));
	memset(amd2, 0, sizeof(md2AnimHold_t));
	amd2->mats = rapi->rpgMatsFromAnim(anim, amd2->numFrames, amd2->frameRate, &amd2->numBones, true);

	return amd2;
}

//index normal into the md2 normals list
static int Model_MD2_IndexNormal(float *nrm)
{
	float bestDP = nrm[0]*g_q2Normals[0][0] + nrm[1]*g_q2Normals[0][1] + nrm[2]*g_q2Normals[0][2];
	int bestIdx = 0;
	for (int i = 1; i < 162; i++)
	{
		float dp = nrm[0]*g_q2Normals[i][0] + nrm[1]*g_q2Normals[i][1] + nrm[2]*g_q2Normals[i][2];
		if (dp > bestDP)
		{
			bestDP = dp;
			bestIdx = i;
		}
	}
	return bestIdx;
}

//bake a frame of vertex data
static void Model_MD2_MakeFrame(sharedModel_t *pmdl, modelMatrix_t *animMats, md2Frame_t *frames, int frameNum, int frameSize, noeRAPI_t *rapi)
{
	md2Frame_t *frame = (md2Frame_t *)((BYTE *)frames + frameSize*frameNum);
	sprintf_s(frame->name, 16, "fr_%i", frameNum);
	float frameMins[3] = {0.0f, 0.0f, 0.0f};
	float frameMaxs[3] = {0.0f, 0.0f, 0.0f};
	if (frameNum > 0 && animMats)
	{ //if working with skeletal data, create/updated the transformed vertex arrays
		rapi->rpgTransformModel(pmdl, animMats, frameNum-1);
	}
	//allocate temporary buffers for the high-precision data
	modelVert_t *vpos = (modelVert_t *)rapi->Noesis_UnpooledAlloc(sizeof(modelVert_t)*pmdl->numAbsVerts);
	modelVert_t *vnrm = (modelVert_t *)rapi->Noesis_UnpooledAlloc(sizeof(modelVert_t)*pmdl->numAbsVerts);
	//fill out high-precision data arrays while calculating the frame bounds
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		sharedVMap_t *svm = pmdl->absVertMap+i;
		sharedMesh_t *mesh = pmdl->meshes+svm->meshIdx;
		modelVert_t *verts = NULL;
		modelVert_t *normals = NULL;
		if (frameNum == 0)
		{ //initial base-pose frame
			verts = mesh->verts+svm->vertIdx;
			normals = mesh->normals+svm->vertIdx;
		}
		else if (frameNum > 0 && animMats)
		{ //bake in skeletally-transformed verts
			verts = mesh->transVerts+svm->vertIdx;
			normals = mesh->transNormals+svm->vertIdx;
		}
		else if (frameNum > 0 && mesh->numMorphFrames > 0 && frameNum-1 < mesh->numMorphFrames)
		{ //copy over vertex morph frames
			verts = mesh->morphFrames[frameNum-1].pos+svm->vertIdx;
			normals = mesh->morphFrames[frameNum-1].nrm+svm->vertIdx;
		}
		modelVert_t *framePos = vpos+i;
		modelVert_t *frameNrm = vnrm+i;
		if (!verts || !normals)
		{ //something went wrong with the transforms
			framePos->x = 0.0f;
			framePos->y = 0.0f;
			framePos->z = 0.0f;
			frameNrm->x = 0.0f;
			frameNrm->y = 0.0f;
			frameNrm->z = 1.0f;
		}
		else
		{
			framePos->x = verts->x;
			framePos->y = verts->y;
			framePos->z = verts->z;
			frameNrm->x = normals->x;
			frameNrm->y = normals->y;
			frameNrm->z = normals->z;
		}
		//add to the frame bounds
		if (i == 0)
		{
			g_mfn->Math_VecCopy((float *)framePos, frameMins);
			g_mfn->Math_VecCopy((float *)framePos, frameMaxs);
		}
		else
		{
			g_mfn->Math_ExpandBounds(frameMins, frameMaxs, (float *)framePos, (float *)framePos);
		}
	}

	//now convert the data to a md2 frame
	frame->trans[0] = frameMins[0];
	frame->trans[1] = frameMins[1];
	frame->trans[2] = frameMins[2];
	const float frange = 255.0f;
	const float invFRange = 1.0f/frange;
	frame->scale[0] = (frameMaxs[0]-frameMins[0])*invFRange;
	frame->scale[1] = (frameMaxs[1]-frameMins[1])*invFRange;
	frame->scale[2] = (frameMaxs[2]-frameMins[2])*invFRange;
	md2Vert_t *md2Verts = (md2Vert_t *)(frame+1);
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		md2Vert_t *lv = md2Verts+i;
		float *hvPos = (float *)(vpos+i);
		float *hvNrm = (float *)(vnrm+i);
		for (int j = 0; j < 3; j++)
		{
			float f = ((hvPos[j]-frameMins[j])/(frameMaxs[j]-frameMins[j])) * frange;
			lv->pos[j] = (BYTE)g_mfn->Math_Min2(f, frange);
		}
		lv->nrmIdx = Model_MD2_IndexNormal(hvNrm);
	}

	rapi->Noesis_UnpooledFree(vpos);
	rapi->Noesis_UnpooledFree(vnrm);
}

//put uv in 0-1 range
static float Model_MD2_CrunchUV(float f)
{
	f = fmodf(f, 1.0f);
	while (f < 0.0f)
	{
		f += 1.0f;
	}
	return f;
}

//create the skin page
BYTE *Model_MD2_CreateSkin(CArrayList<noesisTexRef_t> &trefs, sharedModel_t *pmdl, md2ST_t *sts, int &skinWidth, int &skinHeight, modelTexCoord_t *fuvs, noeRAPI_t *rapi)
{
	if (trefs.Num() <= 0)
	{
		rapi->LogOutput("WARNING: No textures to embed, creating placeholder image.\n");
		skinWidth = 128;
		skinHeight = 128;
		BYTE *page = (BYTE *)rapi->Noesis_UnpooledAlloc(skinWidth*skinHeight);
		for (int i = 0; i < skinWidth*skinHeight; i++)
		{
			page[i] = 15;
		}
		return page;
	}

	skinWidth = 0;
	skinHeight = 0;
	BYTE *page = rapi->Noesis_CreateRefImagePage(trefs, skinWidth, skinHeight);

	//now create new uv's indexing the appropriate sub-textures in the page
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		sharedVMap_t *svm = pmdl->absVertMap + i;
		sharedMesh_t *mesh = pmdl->meshes + svm->meshIdx;
		modelTexCoord_t *uv = fuvs+i;
		if (mesh->uvs && mesh->texRefIdx && mesh->texRefIdx[0] >= 0 && mesh->texRefIdx[0] < trefs.Num())
		{
			modelTexCoord_t *srcUV = mesh->uvs + svm->vertIdx;
			noesisTexRef_t &tref = trefs[mesh->texRefIdx[0]];
			if (tref.t)
			{
				float biasX = (float)tref.pageX / (float)skinWidth;
				float biasY = (float)tref.pageY / (float)skinHeight;
				float scaleX = (float)tref.t->w / (float)skinWidth;
				float scaleY = (float)tref.t->h / (float)skinHeight;
				uv->u = biasX + Model_MD2_CrunchUV(srcUV->u)*scaleX;
				uv->v = biasY + Model_MD2_CrunchUV(srcUV->v)*scaleY;
			}
			else
			{
				uv->u = 0.0f;
				uv->v = 0.0f;
			}
		}
		else
		{
			uv->u = 0.0f;
			uv->v = 0.0f;
		}
	}

	char *mdlskinsizeOpt = rapi->Noesis_GetOption("mdlskinsize");
	if (mdlskinsizeOpt)
	{ //share the mdl-format resize texture page option
		int resizeImg[2] = {0, 0};
		sscanf_s(mdlskinsizeOpt, "%i %i", &resizeImg[0], &resizeImg[1]);
		if (resizeImg[0] && resizeImg[1])
		{
			rapi->LogOutput("Resampling texture page to %ix%i.\n", resizeImg[0], resizeImg[1]);
			BYTE *pageResized = (BYTE *)rapi->Noesis_UnpooledAlloc(resizeImg[0]*resizeImg[1]*4);
			rapi->Noesis_ResampleImageBilinear(page, skinWidth, skinHeight, pageResized, resizeImg[0], resizeImg[1]);
			rapi->Noesis_UnpooledFree(page);
			page = pageResized;
			skinWidth = resizeImg[0];
			skinHeight = resizeImg[1];
		}
	}

	//generate quake st coordinates, with the final page size
	for (int i = 0; i < pmdl->numAbsVerts; i++)
	{
		md2ST_t *qst = sts+i;
		modelTexCoord_t *fuv = fuvs+i;
		qst->st[0] = (short)floorf(Model_MD2_CrunchUV(fuv->u)*(float)skinWidth);
		qst->st[1] = (short)floorf(Model_MD2_CrunchUV(fuv->v)*(float)skinHeight);
	}

	BYTE *pagePal = (BYTE *)rapi->Noesis_UnpooledAlloc(skinWidth*skinHeight);
	BYTE *qpala = &g_q2Pal[0][0];
	
	rapi->LogOutput("Palettizing texture...\n");
	rapi->Noesis_ApplyPaletteRGBA(page, skinWidth, skinHeight, pagePal, qpala);
	rapi->Noesis_UnpooledFree(page);

	return pagePal;
}

//generate the gl command data
BYTE *Model_MD2_GenerateGLCmds(sharedModel_t *pmdl, md2Tri_t *tris, modelTexCoord_t *fuvs, int &glcmdsSize, noeRAPI_t *rapi)
{
	rapi->LogOutput("Generating GL command lists...\n");
	RichBitStream bs;
	bool hasStrips = false;
	sharedStripList_t *slist = NULL;
	int numSList = 0;
	char *md2StripOpt = rapi->Noesis_GetOption("md2strips");
	if (md2StripOpt && atoi(md2StripOpt))
	{
		//convert the triangle indices to a flat short list for ingestion by the stripper
		WORD *triIdx = (WORD *)rapi->Noesis_UnpooledAlloc(sizeof(WORD)*pmdl->numAbsTris*3);
		for (int i = 0; i < pmdl->numAbsTris; i++)
		{
			md2Tri_t *tri = tris+i;
			WORD *dst = triIdx + i*3;
			dst[0] = tri->vidx[0];
			dst[1] = tri->vidx[1];
			dst[2] = tri->vidx[2];
		}
		hasStrips = rapi->rpgGenerateStripLists(triIdx, pmdl->numAbsTris*3, &slist, numSList, false);
		rapi->Noesis_UnpooledFree(triIdx);
	}
	if (!hasStrips)
	{ //if there are no strip lists, plot a plain list
		for (int i = 0; i < pmdl->numAbsTris; i++)
		{
			md2Tri_t *tri = tris+i;
			bs.WriteInt(3);
			md2GLCmd_t glcmds[3];
			for (int j = 0; j < 3; j++)
			{
				glcmds[j].idx = tri->vidx[j];
				glcmds[j].st[0] = fuvs[tri->vidx[j]].u;
				glcmds[j].st[1] = fuvs[tri->vidx[j]].v;
			}
			bs.WriteBytes(glcmds, sizeof(glcmds));
		}
	}
	else
	{ //plot the strips down
		for (int i = 0; i < numSList; i++)
		{
			sharedStripList_t *strip = slist+i;
			if (strip->type == SHAREDSTRIP_LIST)
			{ //plot it down as a list
				for (int j = 0; j < strip->numIdx; j += 3)
				{
					WORD *tri = strip->idx+j;
					bs.WriteInt(3);
					md2GLCmd_t glcmds[3];
					for (int j = 0; j < 3; j++)
					{
						glcmds[j].idx = tri[j];
						glcmds[j].st[0] = fuvs[tri[j]].u;
						glcmds[j].st[1] = fuvs[tri[j]].v;
					}
					bs.WriteBytes(glcmds, sizeof(glcmds));
				}
			}
			else
			{ //plot a strip
				bs.WriteInt(strip->numIdx);
				for (int j = 0; j < strip->numIdx; j++)
				{
					md2GLCmd_t glcmd;
					WORD idx = strip->idx[j];
					glcmd.idx = idx;
					glcmd.st[0] = fuvs[idx].u;
					glcmd.st[1] = fuvs[idx].v;
					bs.WriteBytes(&glcmd, sizeof(glcmd));
				}
			}
		}
	}
	bs.WriteInt(0);

	glcmdsSize = bs.GetSize();
	BYTE *tmp = (BYTE *)rapi->Noesis_UnpooledAlloc(glcmdsSize);
	memcpy(tmp, bs.GetBuffer(), glcmdsSize);
	return tmp;
}

//export the page as pcx (assume q2 palette)
static void Model_MD2_OutputSkinPage(BYTE *pix, int pixW, int pixH, noeRAPI_t *rapi)
{
	char *outName = rapi->Noesis_GetOutputName();
	char outPath[MAX_NOESIS_PATH];
	rapi->Noesis_GetDirForFilePath(outPath, outName);

	strcat_s(outPath, MAX_NOESIS_PATH, "skinpage.pcx");
	if (rapi->Noesis_FileExists(outPath))
	{ //if the file exists, see if the user wants to overwrite it
		HWND wnd = g_nfn->NPAPI_GetMainWnd();
		if (wnd && MessageBox(wnd, L"skinpage.pcx already exists at the specified path. Are you sure you want to overwrite it?", L"MD2 Exporter", MB_YESNO) != IDYES)
		{
			return;
		}
	}

	//grab an extension function for paletted pcx output
	bool (*pcxOut)(char *filename, BYTE *pixData, BYTE *palData, int w, int h);
	*((NOEXFUNCTION *)&pcxOut) = rapi->Noesis_GetExtProc("Image_WritePalettedPCX256");
	if (!pcxOut)
	{
		rapi->LogOutput("WARNING: Image_WritePalettedPCX256 extension unavailable, skipping texture page output.\n");
		return;
	}

	rapi->LogOutput("Writing '%s'.\n", outPath);
	pcxOut(outPath, pix, &g_q2Pal[0][0], pixW, pixH);
}

//export to md2
bool Model_MD2_Write(noesisModel_t *mdl, RichBitStream *outStream, noeRAPI_t *rapi)
{
	sharedModel_t *pmdl = rapi->rpgGetSharedModel(mdl, NMSHAREDFL_WANTGLOBALARRAY|NMSHAREDFL_REVERSEWINDING);
	if (!pmdl)
	{
		return false;
	}

	if (pmdl->numAbsVerts > 65535)
	{ //this is a hard format limit
		rapi->LogOutput("ERROR: numVerts (%i) exceeds 65535!\n", pmdl->numAbsVerts);
		return false;
	}

	rapi->LogOutput("Attempting to fetch textures to bake into MDL...\n");
	CArrayList<noesisTexRef_t> &trefs = rapi->Noesis_LoadTexturesForModel(pmdl);
	rapi->LogOutput("Fetched %i texture(s).\n", trefs.Num());

	if (pmdl->numAbsVerts > 2048)
	{ //warn them if they're exceeding standard format limits
		rapi->LogOutput("WARNING: numVerts (%i) exceeds 2048, model will not work in standard Quake 2 engines.\n", pmdl->numAbsVerts);
	}
	if (pmdl->numAbsTris > 4096)
	{ //warn them if they're exceeding standard format limits
		rapi->LogOutput("WARNING: numTris (%i) exceeds 4096, model will not work in standard Quake 2 engines.\n", pmdl->numAbsTris);
	}

	//first, let's see if the data being exported contains any morph frames. we'll prioritize those over skeletal animation data, although we could also combine them.
	int maxMorphFrames = 0;
	for (int i = 0; i < pmdl->numMeshes; i++)
	{
		sharedMesh_t *mesh = pmdl->meshes+i;
		if (!mesh->morphFrames || mesh->numMorphFrames <= 0)
		{
			continue;
		}
		if (mesh->numMorphFrames > maxMorphFrames)
		{
			maxMorphFrames = mesh->numMorphFrames;
		}
	}

	md2AnimHold_t *amd2 = NULL;
	if (pmdl->bones && pmdl->numBones > 0 && maxMorphFrames <= 0)
	{ //if it's a skeletal mesh and no morph frames were found, look for some skeletal animation data
		amd2 = Model_MD2_GetAnimData(rapi);
		if (amd2 && amd2->numBones != pmdl->numBones)
		{ //got some, but the bone count doesn't match!
			amd2 = NULL;
		}
	}

	int mdlFrames = (amd2) ? 1 + amd2->numFrames : 1 + maxMorphFrames;
	if (mdlFrames > 512)
	{ //warn them if they're exceeding standard format limits
		rapi->LogOutput("WARNING: numFrames (%i) exceeds 512, not compatible with standard Quake 2 network protocol.\n", mdlFrames);
	}

	modelMatrix_t *animMats = (amd2) ? amd2->mats : NULL;

	//now, bake all the frame data out
	rapi->LogOutput("Compressing and encoding frames...\n");
	int frameSize = sizeof(md2Frame_t) + sizeof(md2Vert_t)*pmdl->numAbsVerts;
	md2Frame_t *frames = (md2Frame_t *)rapi->Noesis_UnpooledAlloc(frameSize*mdlFrames);
	for (int i = 0; i < mdlFrames; i++)
	{
		Model_MD2_MakeFrame(pmdl, animMats, frames, i, frameSize, rapi);
	}

	//next, create triangle data
	md2Tri_t *tris = (md2Tri_t *)rapi->Noesis_UnpooledAlloc(pmdl->numAbsTris*sizeof(md2Tri_t));
	for (int i = 0; i < pmdl->numAbsTris; i++)
	{
		modelLongTri_t *src = pmdl->absTris+i;
		md2Tri_t *dst = tris+i;
		dst->vidx[0] = src->idx[0];
		dst->vidx[1] = src->idx[1];
		dst->vidx[2] = src->idx[2];
		dst->stidx[0] = src->idx[0];
		dst->stidx[1] = src->idx[1];
		dst->stidx[2] = src->idx[2];
	}

	md2Hdr_t hdr;
	memset(&hdr, 0, sizeof(hdr));
	memcpy(hdr.id, "IDP2", 4);
	hdr.ver = 8;
	hdr.frameSize = frameSize;
	hdr.numSkins = 1;
	hdr.numVerts = pmdl->numAbsVerts;
	hdr.numST = pmdl->numAbsVerts;
	hdr.numTris = pmdl->numAbsTris;
	hdr.numFrames = mdlFrames;

	//now fill out the st's and create a single texture page
	md2ST_t *sts = (md2ST_t *)rapi->Noesis_UnpooledAlloc(pmdl->numAbsVerts*sizeof(md2ST_t));
	memset(sts, 0, pmdl->numAbsVerts*sizeof(md2ST_t));
	rapi->LogOutput("Compiling texture page(s)...\n");
	modelTexCoord_t *fuvs = (modelTexCoord_t *)rapi->Noesis_UnpooledAlloc(sizeof(modelTexCoord_t)*pmdl->numAbsVerts);
	memset(fuvs, 0, sizeof(modelTexCoord_t)*pmdl->numAbsVerts);
	BYTE *skinPage = Model_MD2_CreateSkin(trefs, pmdl, sts, hdr.skinWidth, hdr.skinHeight, fuvs, rapi);
	int glcmdsSize;
	BYTE *glcmds = Model_MD2_GenerateGLCmds(pmdl, tris, fuvs, glcmdsSize, rapi);
	hdr.numGLCmds = glcmdsSize/4;

	//set skins up
	char *md2painOpt = rapi->Noesis_GetOption("md2painskin");
	bool addPainSkin = (md2painOpt && atoi(md2painOpt));
	md2Skin_t skins[2];
	memset(skins, 0, sizeof(skins));
	char skinName[4096];
	rapi->Noesis_GetDirForFilePath(skinName, pmdl->meshes->skinName); //grab the name path from the first mesh
	strcat_s(skinName, 4096, "skinpage.pcx");
	strcpy_s(skins[0].name, 64, skinName); 
	rapi->LogOutput("Skin path: %s\n", skins[0].name);
	if (addPainSkin)
	{
		rapi->Noesis_GetDirForFilePath(skins[1].name, skins[0].name);
		strcat_s(skins[1].name, 64, "pain.pcx");
		hdr.numSkins++;
	}
	//export the page as pcx
	Model_MD2_OutputSkinPage(skinPage, hdr.skinWidth, hdr.skinHeight, rapi);

	//set up all the offsets
	hdr.ofsSkins = sizeof(hdr);
	hdr.ofsST = hdr.ofsSkins + sizeof(md2Skin_t)*hdr.numSkins;
	hdr.ofsTris = hdr.ofsST + sizeof(md2ST_t)*hdr.numST;
	hdr.ofsFrames = hdr.ofsTris + sizeof(md2Tri_t)*hdr.numTris;
	hdr.ofsGLCmds = hdr.ofsFrames + frameSize*hdr.numFrames;
	hdr.ofsEnd = hdr.ofsGLCmds + glcmdsSize;

	//now write it all to the output stream
	outStream->WriteBytes(&hdr, sizeof(hdr));
	outStream->WriteBytes(skins, sizeof(md2Skin_t)*hdr.numSkins);
	outStream->WriteBytes(sts, sizeof(md2ST_t)*hdr.numST);
	outStream->WriteBytes(tris, sizeof(md2Tri_t)*hdr.numTris);
	outStream->WriteBytes(frames, frameSize*hdr.numFrames);
	outStream->WriteBytes(glcmds, glcmdsSize);

	rapi->Noesis_UnpooledFree(glcmds);
	rapi->Noesis_UnpooledFree(skinPage);
	rapi->Noesis_UnpooledFree(fuvs);
	rapi->Noesis_UnpooledFree(frames);
	rapi->Noesis_UnpooledFree(tris);
	rapi->Noesis_UnpooledFree(sts);

	return true;
}

//catch anim writes
//(note that this function would normally write converted data to a file at anim->filename, but for this format it instead saves the data to combine with the model output)
void Model_MD2_WriteAnim(noesisAnim_t *anim, noeRAPI_t *rapi)
{
	if (!rapi->Noesis_HasActiveGeometry() || rapi->Noesis_GetActiveType() != g_fmtHandle)
	{
		rapi->LogOutput("WARNING: Stand-alone animations cannot be converted to MD2.\nNothing will be written.\n");
		return;
	}

	rapi->Noesis_SetExtraAnimData(anim->data, anim->dataLen);
}
