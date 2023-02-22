//Thanks to Satoh for sending me a lot of specs for these formats.
//Thanks to Zidane2, Zande, Chev, and possibly others for those original specs. Unfortunately, proper credits are omitted from the docs I'm basing this code on.

#include "stdafx.h"
#include "ff9types.h"

extern bool Model_FF9_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi);
extern noesisModel_t *Model_FF9_Load(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi);
extern bool Model_FF9_CheckAnim(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi);
extern noesisModel_t *Model_FF9_LoadAnim(BYTE *fileBuffer, int bufferLen, int &numMdl, noeRAPI_t *rapi);

const char *g_pPluginName = "ff9psx_img_mdl";
const char *g_pPluginDesc = "FF9 handler, by Dick.";

static bool g_unpackDB = false;

static const char *g_ff9DbTypes[16] =
{
	"raw00",		//0
	"raw01",		//1
	"ff9mdl",		//2
	"ff9anm",		//3
	"tim",			//4
	"ff9script",	//5
	"raw06",		//6
	"raw07",		//7
	"akao",			//8
	"raw09",		//9
	"ff9tiles",		//10
	"ff9wm",		//11
	"raw12",		//12
	"raw13",		//13
	"raw14",		//14
	"raw15"			//15
};

//set recursive unpack preference
static void SetRecursiveDBUnpack(void)
{
	g_unpackDB = false;
	HWND noeWnd = g_nfn->NPAPI_GetMainWnd();
	if (noeWnd)
	{
		if (MessageBox(noeWnd, L"Would you like to recursively unpack .ff9db files? This can take a long time, and produce many thousands of files.", L"FF9 Plugin", MB_YESNO) == IDYES)
		{
			g_unpackDB = true;
		}
	}
}

//get offset for a file pack
static ff9dbFilePakHdr_t *GetFF9DBPakOfs(BYTE *fileBuffer, ff9dbEntry_t *entries, int idx, int &ofs)
{
	ff9dbEntry_t *e = entries+idx;
	ofs = sizeof(ff9dbHdr_t) + e->ofs + idx*4;
	ff9dbFilePakHdr_t *pakHdr = (ff9dbFilePakHdr_t *)(fileBuffer + ofs);
	ofs += sizeof(ff9dbFilePakHdr_t);
	int unkSize = AlignInt(sizeof(WORD)*pakHdr->numFiles, 4);
	ofs += unkSize;
	return pakHdr;
}

//do actual extraction (can be called from img extraction too)
static bool ExtractFF9DBEx(char *basePath, BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	ff9dbHdr_t *hdr = (ff9dbHdr_t *)fileBuffer;
	int numEntries = (int)hdr->numEntries;

	char tmp[64];
	ff9dbEntry_t *entries = (ff9dbEntry_t *)(hdr+1);
	int numFiles = 0;
	for (int i = 0; i < numEntries; i++)
	{
		int ofs, nOfs;
		ff9dbFilePakHdr_t *pakHdr = GetFF9DBPakOfs(fileBuffer, entries, i, ofs);
		int *filesOfs = (int *)(fileBuffer + ofs);
		int *nFilesOfs = NULL;
		if (i < numEntries-1)
		{ //get the next offset table to determine size of the last entry
			ff9dbFilePakHdr_t *nPakHdr = GetFF9DBPakOfs(fileBuffer, entries, i+1, nOfs);
			if (nPakHdr->numFiles > 0)
			{
				nFilesOfs = (int *)(fileBuffer+nOfs);
			}
		}
		for (int j = 0; j < pakHdr->numFiles; j++)
		{
			int fileOfs = filesOfs[j];
			int absOfs = ofs + fileOfs + j*sizeof(int);
			int fileSize;
			if (j < pakHdr->numFiles-1)
			{
				fileSize = (filesOfs[j+1]-filesOfs[j])+sizeof(int);
			}
			else if (nFilesOfs)
			{
				fileSize = (nOfs+nFilesOfs[0]) - absOfs;
			}
			else
			{
				fileSize = bufferLen-absOfs;
				assert(i == numEntries-1 && j == pakHdr->numFiles-1);
			}
			assert(fileSize > 0 && ofs+fileOfs+fileSize <= bufferLen);
			BYTE *buf = fileBuffer + absOfs;
			char fn[MAX_NOESIS_PATH];
			const char *fext;
			if (pakHdr->type < 16)
			{
				fext = g_ff9DbTypes[pakHdr->type];
			}
			else if (pakHdr->type == 27)
			{
				strcpy_s(tmp, 64, "ff9db");
				fext = tmp;
			}
			else
			{
				sprintf_s(tmp, 64, "raw%02i", pakHdr->type);
				fext = tmp;
			}
			if (g_unpackDB && pakHdr->type == 27)
			{ //recursively unpack it
				sprintf_s(fn, MAX_NOESIS_PATH, "%sdbfile%04i_files/", basePath, numFiles);
				rapi->LogOutput("Unpacking nested FF9DB...\n");
				ExtractFF9DBEx(fn, buf, fileSize, rapi);
			}
			sprintf_s(fn, MAX_NOESIS_PATH, "%sdbfile%04i.%s", basePath, numFiles, fext);
			rapi->LogOutput("Writing '%s'.\n", fn);
			rapi->Noesis_ExportArchiveFile(fn, buf, fileSize);
			numFiles++;
		}
	}

	return true;
}

//read a file, then export it
static void WriteFF9IMGFile(RichFileWrap &imgFile, int dirNum, int fileNum, __int64 ofs, __int64 size, noeRAPI_t *rapi)
{
	BYTE *buf = (BYTE *)rapi->Noesis_UnpooledAlloc((size_t)size);
	imgFile.Seek(ofs, false);
	imgFile.Read(buf, size);

	char baseStr[MAX_NOESIS_PATH];
	sprintf_s(baseStr, MAX_NOESIS_PATH, "dir%02i/file%04i", dirNum, fileNum);
	char fn[MAX_NOESIS_PATH];
	char *fext = rapi->Noesis_GuessFileExt(buf, (int)size);
	sprintf_s(fn, MAX_NOESIS_PATH, "%s.%s", baseStr, fext);
	rapi->LogOutput("Writing '%s'.\n", fn);
	rapi->Noesis_ExportArchiveFile(fn, buf, (int)size);
	if (g_unpackDB && !strcmp(fext, "ff9db"))
	{
		rapi->LogOutput("Auto-unpacking '%s'...\n", fn);
		strcat_s(baseStr, MAX_NOESIS_PATH, "_files/");
		ExtractFF9DBEx(baseStr, buf, (int)size, rapi);
	}

	rapi->Noesis_UnpooledFree(buf);
}

//when using the stream archive handler, you are responsible for managing the file handle yourself.
static bool ExtractFF9IMG(wchar_t *filename, __int64 len, bool justChecking, noeRAPI_t *rapi)
{
	if (len < sizeof(ff9ImgHdr_t))
	{
		return false;
	}
	RichFileWrap f(filename, NOEFSMODE_READBINARY, rapi);
	if (!f.IsValid())
	{
		return false;
	}

	ff9ImgHdr_t hdr;
	f.Read(&hdr, sizeof(hdr));
	if (memcmp(hdr.id, "FF9 ", 4) || hdr.dirNum <= 0)
	{
		return false;
	}

	if (justChecking)
	{
		return true;
	}

	SetRecursiveDBUnpack();

	const __int64 secSh = 11; //2048

	ff9ImgDir_t *dirs = (ff9ImgDir_t *)rapi->Noesis_UnpooledAlloc(sizeof(ff9ImgDir_t)*hdr.dirNum);
	f.Read(dirs, sizeof(ff9ImgDir_t)*hdr.dirNum);
	for (int i = 0; i < hdr.dirNum; i++)
	{
		ff9ImgDir_t *dir = dirs+i;
		if (dir->type == 2)
		{
			if (dir->fileNum > 0)
			{
				f.Seek(dir->fileInfoOfs << secSh, false);
				int readInfoNum = dir->fileNum+1;
				ff9ImgFileInfo_t *infos = (ff9ImgFileInfo_t *)rapi->Noesis_UnpooledAlloc(sizeof(ff9ImgFileInfo_t)*readInfoNum);
				f.Read(infos, sizeof(ff9ImgFileInfo_t)*readInfoNum);
				assert(infos[readInfoNum-1].flags == -1); //should always have an end marker at the end of a directory listing
				for (int j = 0; j < dir->fileNum; j++)
				{
					ff9ImgFileInfo_t *info = infos+j;
					if (info->flags == -1)
					{
						continue;
					}
					__int64 ofs = (__int64)info->fileOfs << secSh;
					__int64 size = ((__int64)infos[j+1].fileOfs << secSh) - ofs;
					WriteFF9IMGFile(f, i, j, ofs, size, rapi);
				}
				rapi->Noesis_UnpooledFree(infos);
			}
		}
		else if (dir->type == 3)
		{
			f.Seek(dir->fileInfoOfs << secSh, false);
			int readInfoNum = dir->fileNum+1;
			WORD *sofs = (WORD *)rapi->Noesis_UnpooledAlloc(sizeof(WORD)*readInfoNum);
			f.Read(sofs, sizeof(WORD)*readInfoNum);
			WORD lastOfs = 0xFFFF;
			for (int j = 0; j < readInfoNum; j++)
			{
				if (sofs[j] == 0xFFFF)
				{
					continue;
				}
				if (lastOfs != 0xFFFF)
				{
					__int64 ofs = ((__int64)dir->firstFileOfs + (__int64)lastOfs) << secSh;
					__int64 size = ((__int64)sofs[j] - (__int64)lastOfs) << secSh;
					WriteFF9IMGFile(f, i, j, ofs, size, rapi);
				}
				lastOfs = sofs[j];
			}
		}
		else
		{
			break;
		}
	}

	rapi->Noesis_UnpooledFree(dirs);
	return true;
}

//extract db package
bool ExtractFF9DB(BYTE *fileBuffer, int bufferLen, bool justChecking, noeRAPI_t *rapi)
{
	if (bufferLen <= sizeof(ff9dbHdr_t))
	{
		return false;
	}
	ff9dbHdr_t *hdr = (ff9dbHdr_t *)fileBuffer;
	int numEntries = (int)hdr->numEntries;
	if (numEntries <= 0)
	{
		return false;
	}
	int eend = sizeof(ff9dbHdr_t) + sizeof(ff9dbEntry_t)*numEntries;
	if (eend <= 0 || eend >= bufferLen)
	{
		return false;
	}

	if (justChecking)
	{
		return true;
	}

	//SetRecursiveDBUnpack();
	g_unpackDB = true;

	return ExtractFF9DBEx("", fileBuffer, bufferLen, rapi);
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	if (g_nfn->NPAPI_GetAPIVersion() < NOESIS_PLUGINAPI_VERSION)
	{
		return false;
	}

	int fh;
	//main img file
	fh = g_nfn->NPAPI_Register("FF9 IMG", ".img");
	if (fh < 0)
	{
		return false;
	}
	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_ExtractArcStream(fh, ExtractFF9IMG);

	//"db" files
	fh = g_nfn->NPAPI_Register("FF9DB Package", ".ff9db");
	if (fh < 0)
	{
		return false;
	}
	//set the data handlers for this format (these are all pretty small, so just use the in-memory handler)
	g_nfn->NPAPI_SetTypeHandler_ExtractArc(fh, ExtractFF9DB);

	//ff9mdl files
	fh = g_nfn->NPAPI_Register("FF9 Model", ".ff9mdl");
	if (fh < 0)
	{
		return false;
	}
	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fh, Model_FF9_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fh, Model_FF9_Load);

	//ff9anm files
	fh = g_nfn->NPAPI_Register("FF9 Anim", ".ff9anm");
	if (fh < 0)
	{
		return false;
	}
	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(fh, Model_FF9_CheckAnim);
	g_nfn->NPAPI_SetTypeHandler_LoadModel(fh, Model_FF9_LoadAnim);

	return true;
}

//called by Noesis before the plugin is freed
void NPAPI_ShutdownLocal(void)
{
	//nothing to do here
}

BOOL APIENTRY DllMain( HMODULE hModule,
                       DWORD  ul_reason_for_call,
                       LPVOID lpReserved
					 )
{
    return TRUE;
}
