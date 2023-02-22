#include "../../pluginshare.h"
#include <math.h>

typedef struct md2Hdr_s
{
	BYTE			id[4];
	int				ver;

	int				skinWidth;
	int				skinHeight;
	int				frameSize;
	int				numSkins;
	int				numVerts;
	int				numST;
	int				numTris;
	int				numGLCmds;
	int				numFrames;

	int				ofsSkins;
	int				ofsST;
	int				ofsTris;
	int				ofsFrames;
	int				ofsGLCmds;
	int				ofsEnd;
} md2Hdr_t;
typedef struct md2Skin_s
{
	char			name[64];
} md2Skin_t;
typedef struct md2ST_s
{
	short			st[2];
} md2ST_t;
typedef struct md2Tri_s
{
	WORD			vidx[3];
	WORD			stidx[3];
} md2Tri_t;
typedef struct md2Vert_s
{
	BYTE			pos[3];
	BYTE			nrmIdx;
} md2Vert_t;
typedef struct md2Frame_s
{
	float			scale[3];
	float			trans[3];
	char			name[16];
} md2Frame_t;
typedef struct md2GLCmd_s
{
	float			st[2];
	int				idx;
} md2GLCmd_t;

extern mathImpFn_t *g_mfn;
extern noePluginFn_t *g_nfn;
extern int g_fmtHandle;

extern float g_q2Normals[162][3];
extern BYTE g_q2Pal[256][4];

NPLUGIN_API bool NPAPI_Init(void);
NPLUGIN_API void NPAPI_Shutdown(void);
NPLUGIN_API int NPAPI_GetPluginVer(void);
