#include "../../pluginshare.h"
#include <math.h>

typedef struct pskOpts_s
{
	int					keepBoneSpaces;
} pskOpts_t;

typedef struct pskChunk_s
{
	char			id[20];
	int				version;
	int				recSize;
	int				numRec;
} pskChunk_t;

typedef struct pskVert_s
{
	WORD			pointIdx;
	
	WORD			padA;
	
	float			tc[2];
	BYTE			matIdx; //don't know why this is here, when the triangle provides it. per-vertex materials would be silly.

	BYTE			padB[3];
} pskVert_t;

typedef struct pskFace_s
{
	WORD			idx[3];
	BYTE			matIdx;
	BYTE			pad;
	DWORD			group;
} pskFace_t;

typedef struct pskMaterial_s
{
	char			name[64];
	int				unknown[6];
} pskMaterial_t;

typedef struct pskBone_s
{
	char			name[64];
	int				unknownA;
	int				numChildren;
	int				parent;

	RichQuat		rot;
	RichVec3		trans;
	float			unknownB;
	RichVec3		size;
} pskBone_t;

typedef struct pskWeight_s
{
	float			w;
	int				pointIdx;
	int				boneIdx;
} pskWeight_t;

typedef struct psaAnimInfo_s
{
	char			name[64];
	char			group[64];
	int				numBones;
	int				rootInc;
	int				keyCompStyle;
	int				keyNum; //numBones*numFrames
	float			unknownB;
	float			duration;
	float			frameRate;
	int				unknownC;
	int				firstFrame;
	int				numFrames;
} psaAnimInfo_t;

typedef struct psaAnimKey_s
{
	RichVec3		trans;
	RichQuat		rot;
	float			frameTime;
} psaAnimKey_t;


//only used for processing
typedef struct pskWEntry_s
{
	pskWeight_t		*w;
	pskWEntry_s		*next;
} pskWEntry_t;
typedef struct pskWList_s
{
	int				numWeights;
	pskWEntry_t		*weights;
} pskWList_t;
typedef struct pskTriNrm_s
{
	RichVec3		nrm[3];
} pskTriNrm_t;
typedef struct pskTriPlane_s
{
	float			p[4];
} pskTriPlane_t;
typedef struct pskPosW_s
{
	RichVec3		v;
	int				boneIdx[4];
	float			boneWgt[4];
} pskPosW_t;
typedef struct pskTriRef_s
{
	int				triIdx;
	int				ptIdx;
	pskTriRef_s		*next;
} pskTriRef_t;
typedef struct pskTriRefL_s
{
	pskTriRef_t		*refList;
	int				numRefs;
} pskTriRefL_t;
