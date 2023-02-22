typedef struct ff9ImgDir_s
{
	int				type;
	int				fileNum;
	int				fileInfoOfs;
	int				firstFileOfs;
} ff9ImgDir_t;
typedef struct ff9ImgHdr_s
{
	char			id[4]; //"FF9 "
	int				unkA;
	int				dirNum;
	int				unkB;
} ff9ImgHdr_t;
typedef struct ff9ImgFileInfo_s
{
	int				flags;
	int				fileOfs;
} ff9ImgFileInfo_t;

typedef struct ff9dbHdr_s
{
	BYTE			id; //0xDB
	BYTE			numEntries;
	BYTE			resv[2];
} ff9dbHdr_t;
typedef struct ff9dbEntry_s
{
	int				ofs:24;
	int				type:8;
} ff9dbEntry_t;
typedef struct ff9dbFilePakHdr_s
{
	BYTE			type;
	BYTE			numFiles;
	BYTE			resv[2];
} ff9dbFilePakHdr_t;

typedef struct ff9MdlHdr_s
{
	WORD			unkA;
	BYTE			numBones;
	BYTE			numMeshes;
	WORD			unkB[4];
	int				bonesOfs;
	int				meshesOfs;
} ff9MdlHdr_t;
typedef struct ff9MdlBone_s
{
	short			len;
	BYTE			unk;
	BYTE			parentIdx;
} ff9MdlBone_t;
typedef struct ff9MdlMesh_s
{
	WORD			meshSize;
	WORD			numQuadsA;
	WORD			numTrisA;
	WORD			numQuadsB;
	WORD			numTrisB;
	WORD			numQuadsC;
	WORD			numTrisC;
	WORD			meshAOfs;
	WORD			meshBOfs;
	WORD			meshCOfs;
	int				boneDataOfs;
	int				vertDataOfs;
	int				polyDataOfs;
	int				uvDataOfs;
	int				endOfs;
} ff9MdlMesh_t;
typedef struct ff9MdlVert_s
{
	short			pos[3];
	BYTE			boneIdx;
	BYTE			unk;
} ff9MdlVert_t;
typedef struct ff9MdlUV_s
{
	BYTE			uv[2];
} ff9MdlUV_t;
typedef struct ff9MdlQuadA_s
{
	WORD			vIdx[4];
	WORD			uvIdx[4];
	BYTE			rgb[3];
	BYTE			texIdx;
	DWORD			unk;
} ff9MdlQuadA_t;
typedef struct ff9MdlTriA_s
{
	WORD			vIdx[3];
	BYTE			texIdx;
	BYTE			unk;
	BYTE			rbg[3];
	BYTE			unkB;
	WORD			uvIdx[3];
	WORD			unkC;
} ff9MdlTriA_t;

typedef struct ff9AnimHdr_s
{
	WORD			unk;
	WORD			numFrames;
	short			rootPosInfo[4];
	int				boneAngHiOfs;
	int				boneAngLoOfs;
} ff9AnimHdr_t;