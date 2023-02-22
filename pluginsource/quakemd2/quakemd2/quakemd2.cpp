//General requirements and/or suggestions for Noesis plugins:
//
// -Use 1-byte struct alignment for all shared structures. (plugin MSVC project file defaults everything to 1-byte-aligned)
// -Always clean up after yourself. Your plugin stays in memory the entire time Noesis is loaded, so you don't want to crap up the process heaps.
// -Try to use reliable type-checking, to ensure your plugin doesn't conflict with other file types and create false-positive situations.
// -Really try not to write crash-prone logic in your data check function! This could lead to Noesis crashing from trivial things like the user browsing files.
// -When using the rpg begin/end interface, always make your Vertex call last, as it's the function which triggers a push of the vertex with its current attributes.
// -!!!! Check the web site and documentation for updated suggestions/info! !!!!

#include "stdafx.h"
#include "quakemd2.h"
#include "q2nrm.h"
#include "q2pal.h"

extern bool Model_MD2_Write(noesisModel_t *mdl, RichBitStream *outStream, noeRAPI_t *rapi);
extern void Model_MD2_WriteAnim(noesisAnim_t *anim, noeRAPI_t *rapi);

const char *g_pPluginName = "quakemd2";
const char *g_pPluginDesc = "Quake II MD2 format handler, by Dick.";
int g_fmtHandle = -1;

//is it this format?
bool Model_MD2_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(md2Hdr_t))
	{
		return false;
	}
	md2Hdr_t *hdr = (md2Hdr_t *)fileBuffer;
	if (memcmp(hdr->id, "IDP2", 4))
	{
		return false;
	}
	if (hdr->ver != 8)
	{
		return false;
	}
	if (hdr->ofsEnd <= 0 || hdr->ofsEnd > bufferLen)
	{
		return false;
	}
	if (hdr->ofsSkins <= 0 || hdr->ofsSkins > bufferLen ||
		hdr->ofsST <= 0 || hdr->ofsST > bufferLen ||
		hdr->ofsTris <= 0 || hdr->ofsTris > bufferLen ||
		hdr->ofsFrames <= 0 || hdr->ofsFrames > bufferLen ||
		hdr->ofsGLCmds <= 0 || hdr->ofsGLCmds > bufferLen ||
		hdr->ofsEnd <= 0 || hdr->ofsEnd > bufferLen)
	{
		return false;
	}

	return true;
}

//decode a vert
static void Model_MD2_DecodeVert(md2Frame_t *frame, md2Vert_t *vert, float *pos, float *nrm)
{
	assert(vert->nrmIdx < 162);
	nrm[0] = g_q2Normals[vert->nrmIdx][0];
	nrm[1] = g_q2Normals[vert->nrmIdx][1];
	nrm[2] = g_q2Normals[vert->nrmIdx][2];
	pos[0] = (float)vert->pos[0] * frame->scale[0] + frame->trans[0];
	pos[1] = (float)vert->pos[1] * frame->scale[1] + frame->trans[1];
	pos[2] = (float)vert->pos[2] * frame->scale[2] + frame->trans[2];
}

//decode st's
static void Model_MD2_DecodeST(md2Hdr_t *hdr, short *st, float *uv)
{
	uv[0] = (float)st[0] / (float)hdr->skinWidth;
	uv[1] = (float)st[1] / (float)hdr->skinHeight;
}

//load it (note that you don't need to worry about validation here, if it was done in the Check function)
noesisModel_t *Model_MD2_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi)
{
	md2Hdr_t *hdr = (md2Hdr_t *)fileBuffer;
	md2Skin_t *skins = (md2Skin_t *)(fileBuffer+hdr->ofsSkins);
	md2ST_t *sts = (md2ST_t *)(fileBuffer+hdr->ofsST);
	md2Tri_t *tris = (md2Tri_t *)(fileBuffer+hdr->ofsTris);
	int frameSize = hdr->frameSize;

	void *pgctx = rapi->rpgCreateContext();

	for (int j = 1; j < hdr->numFrames; j++)
	{ //commit extra frames as morph frames
		int frameNum = 0;
		md2Frame_t *frame = (md2Frame_t *)(fileBuffer+hdr->ofsFrames + frameSize*j);
		md2Vert_t *vertData = (md2Vert_t *)(frame+1);
		float *xyz = (float *)rapi->Noesis_PooledAlloc(sizeof(float)*3*hdr->numVerts);
		float *nrm = (float *)rapi->Noesis_PooledAlloc(sizeof(float)*3*hdr->numVerts);
		for (int k = 0; k < hdr->numVerts; k++)
		{
			Model_MD2_DecodeVert(frame, vertData+k, xyz+k*3, nrm+k*3);
		}
		rapi->rpgFeedMorphTargetPositions(xyz, RPGEODATA_FLOAT, sizeof(float)*3);
		rapi->rpgFeedMorphTargetNormals(nrm, RPGEODATA_FLOAT, sizeof(float)*3);
		rapi->rpgCommitMorphFrame(hdr->numVerts);
	}
	rapi->rpgCommitMorphFrameSet();

	//set the default material name
	rapi->rpgSetMaterial(skins->name);

	//now render out the base frame geometry
	md2Frame_t *frame = (md2Frame_t *)(fileBuffer+hdr->ofsFrames);
	md2Vert_t *vertData = (md2Vert_t *)(frame+1);
	rapi->rpgBegin(RPGEO_TRIANGLE);
	for (int i = 0; i < hdr->numTris; i++)
	{
		md2Tri_t *tri = tris+i;
		for (int j = 2; j >= 0; j--) //loop backwards because q2 had reverse face windings
		{
			float pos[3];
			float nrm[3];
			float uv[2];
			Model_MD2_DecodeVert(frame, &vertData[tri->vidx[j]], pos, nrm);
			Model_MD2_DecodeST(hdr, sts[tri->stidx[j]].st, uv);

			rapi->rpgVertUV2f(uv, 0);
			rapi->rpgVertNormal3f(nrm);
			rapi->rpgVertMorphIndex(tri->vidx[j]); //this is important to tie this vertex to the pre-provided morph arrays
			rapi->rpgVertex3f(pos);
		}
	}
	rapi->rpgEnd();

	rapi->rpgOptimize();
	noesisModel_t *mdl = rapi->rpgConstructModel();
	if (mdl)
	{
		numMdl = 1; //it's important to set this on success! you can set it to > 1 if you have more than 1 contiguous model in memory
		rapi->SetPreviewAnimSpeed(10.0f);
		//this'll rotate the model (only in preview mode) into quake-friendly coordinates
		static float mdlAngOfs[3] = {0.0f, 180.0f, 0.0f};
		rapi->SetPreviewAngOfs(mdlAngOfs);
	}

	rapi->rpgDestroyContext(pgctx);
	return mdl;
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	g_fmtHandle = g_nfn->NPAPI_Register("Quake II MD2", ".md2");
	if (g_fmtHandle < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(g_fmtHandle, Model_MD2_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(g_fmtHandle, Model_MD2_Load);
	//export functions
	g_nfn->NPAPI_SetTypeHandler_WriteModel(g_fmtHandle, Model_MD2_Write);
	g_nfn->NPAPI_SetTypeHandler_WriteAnim(g_fmtHandle, Model_MD2_WriteAnim);

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
