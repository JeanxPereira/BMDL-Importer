//thanks to revelation for the file spec.
//only tested on the Prime Trilogy data. it may or may not work on the individual games.

#include "stdafx.h"

const char *g_pPluginName = "metroidprime_pak";
const char *g_pPluginDesc = "Metroid Prime PAK handler, by Dick.";

typedef struct pakHdr_s
{
	WORD			verMajor;
	WORD			verMinor;
	DWORD			resv;
	DWORD			numNames;
} pakHdr_t;
typedef struct pakFileInfo_s
{
	int				flags;
	char			type[4];
	__int64			id; //likely a hash for the filename
	int				size;
	int				ofs;
} pakFileInfo_t;
typedef struct txtrHdr_s
{
	DWORD			format;
	WORD			w;
	WORD			h;
	DWORD			numMips;
} txtrHdr_t;
typedef struct cmpdHdrv1_s
{
	char			id[4]; //"CMPD"
	DWORD			ver;
	DWORD			compSize;
	DWORD			decompSize;
} cmpdHdrv1_t;
typedef struct cmpdHdrv2_s
{
	char			id[4]; //"CMPD"
	DWORD			ver;
	DWORD			unknownA;
	DWORD			unknownB;
	DWORD			compSize;
	DWORD			decompSize;
	txtrHdr_t		texHdr;
} cmpdHdrv2_t;
typedef struct cmpdHdrv3_s
{
	char			id[4]; //"CMPD"
	DWORD			ver;
	DWORD			unknownA;
	DWORD			unknownB;
	DWORD			compSizeA;
	DWORD			decompSizeA;
	DWORD			compSizeB;
	DWORD			decompSizeB;
	txtrHdr_t		texHdr;
	DWORD			palInfoA;
	DWORD			palInfoB;
} cmpdHdrv3_t;

//if justChecking is true, it's only a query to check the file type. don't do any extraction unless justChecking is false.
bool Model_PAK_ExportFromFile(FILE *f, __int64 len, bool justChecking, noeRAPI_t *rapi)
{
	pakHdr_t hdr;
	fread(&hdr, sizeof(hdr), 1, f);
	LITTLE_BIG_SWAP(hdr.verMajor);
	LITTLE_BIG_SWAP(hdr.verMinor);
	LITTLE_BIG_SWAP(hdr.numNames);
	bool wideID = false;
	if (hdr.numNames <= 0)
	{
		return false;
	}
	if (hdr.verMajor != 3 || hdr.verMinor != 5)
	{
		if (hdr.verMajor != 0 || hdr.verMinor != 2)
		{
			return false;
		}
		wideID = true; //prime 3
	}

	DWORD sectJump = 0;
	DWORD dataOfs = 0;
	if (wideID)
	{ //read over section info
		_fseeki64(f, 0x40, SEEK_SET);
		int numSect = 0;
		fread(&numSect, sizeof(numSect), 1, f);
		LITTLE_BIG_SWAP(numSect);
		if (numSect <= 0)
		{
			return false;
		}
		//read two sections in
		char sectTag[4];
		DWORD sectLen;
		fread(sectTag, sizeof(sectTag), 1, f);
		fread(&sectLen, sizeof(sectLen), 1, f);
		LITTLE_BIG_SWAP(sectLen);
		if (sectLen <= 0)
		{
			return false;
		}
		sectJump = sectLen;
		fread(sectTag, sizeof(sectTag), 1, f);
		fread(&sectLen, sizeof(sectLen), 1, f);
		LITTLE_BIG_SWAP(sectLen);
		dataOfs = 0x80 + sectJump + sectLen;

		_fseeki64(f, 0x80, SEEK_SET);
		fread(&hdr.numNames, sizeof(hdr.numNames), 1, f);
		LITTLE_BIG_SWAP(hdr.numNames);
		if (hdr.numNames <= 0)
		{
			return false;
		}
	}

	for (DWORD i = 0; i < hdr.numNames; i++)
	{
		if (wideID)
		{ //read over the name
			BYTE b = 1;
			while (b)
			{
				size_t r = fread(&b, 1, 1, f);
				if (r != 1)
				{
					return false;
				}
			}
		}
		char type[4];
		int nameLen = 0;
		fread(type, sizeof(type), 1, f);
		if (wideID)
		{ //newer version of the format uses 64-bit hashes
			__int64 id;
			fread(&id, sizeof(id), 1, f);
			LITTLE_BIG_SWAP(id);
		}
		else
		{
			int id;
			fread(&id, sizeof(id), 1, f);
			LITTLE_BIG_SWAP(id);
		}
		if (wideID)
		{
			continue;
		}

		fread(&nameLen, sizeof(nameLen), 1, f);
		LITTLE_BIG_SWAP(nameLen);
		if (nameLen <= 0 || nameLen >= len)
		{
			return false;
		}
		char fn[MAX_NOESIS_PATH];
		size_t r = fread(fn, 1, nameLen, f);
		if (r != nameLen)
		{
			return false;
		}
		/*
		fn[fnHdr.nameLen] = 0;
		char fext[5];
		memcpy(fext, fnHdr.type, 4);
		fext[4] = 0;
		strcat_s(fn, MAX_NOESIS_PATH, ".");
		strcat_s(fn, MAX_NOESIS_PATH, fext);
		*/
	}

	if (sectJump)
	{ //prime 3
		_fseeki64(f, 0x80+sectJump, SEEK_SET);
	}

	int numFileInfo = 0;
	fread(&numFileInfo, sizeof(int), 1, f);
	LITTLE_BIG_SWAP(numFileInfo);
	int infoSize = (wideID) ? 24 : 20;
	int infoSizeTotal = infoSize*numFileInfo;
	if (numFileInfo <= 0 || infoSizeTotal <= 0 || infoSizeTotal >= len)
	{
		return false;
	}

	if (justChecking)
	{ //don't go any further if only validating data
		return true;
	}

	CArrayList<pakFileInfo_t> fileEntries;
	for (int i = 0; i < numFileInfo; i++)
	{
		pakFileInfo_t fi;
		fread(&fi.flags, sizeof(fi.flags), 1, f);
		fread(fi.type, sizeof(fi.type), 1, f);
		if (wideID)
		{
			fread(&fi.id, sizeof(fi.id), 1, f);
			LITTLE_BIG_SWAP(fi.id);
		}
		else
		{
			DWORD id;
			fread(&id, sizeof(id), 1, f);
			LITTLE_BIG_SWAP(id);
			fi.id = id;
		}
		fread(&fi.size, sizeof(fi.size), 1, f);
		fread(&fi.ofs, sizeof(fi.ofs), 1, f);
		LITTLE_BIG_SWAP(fi.flags);
		LITTLE_BIG_SWAP(fi.size);
		LITTLE_BIG_SWAP(fi.ofs);
		fileEntries.Append(fi);
	}
	rapi->LogOutput("Parsed out %i file entries.\n", fileEntries.Num());

	//now write the entries out
	for (int i = 0; i < fileEntries.Num(); i++)
	{
		pakFileInfo_t &fi = fileEntries[i];
		char fext[5];
		memcpy(fext, fi.type, 4);
		fext[4] = 0;
		char fname[MAX_NOESIS_PATH];
		DWORD idA = (DWORD)(fi.id & 0xFFFFFFFF);
		DWORD idB = (DWORD)((fi.id>>32) & 0xFFFFFFFF);
		sprintf_s(fname, MAX_NOESIS_PATH, "mppak%08x%08x.%s", idB, idA, fext);
		BYTE *rawData = (BYTE *)rapi->Noesis_UnpooledAlloc(fi.size);
		_fseeki64(f, fi.ofs+dataOfs, SEEK_SET);
		fread(rawData, 1, fi.size, f);
		
		DWORD writeSize = fi.size;
		if (fi.flags > 0)
		{ //compressed
			assert(fi.size >= 4);
			DWORD compSize;
			DWORD decompSize;
			int compHdrSize = 4;
			BYTE *pfxData = NULL;
			DWORD pfxDataSize = 0;
			if (wideID)
			{ //mp3
				assert(!memcmp(rawData, "CMPD", 4));
				int ver = *((int *)(rawData+4));
				LITTLE_BIG_SWAP(ver);
				if (ver == 3)
				{
					cmpdHdrv3_t cmpdHdr = *((cmpdHdrv3_t *)rawData);
					compHdrSize = sizeof(cmpdHdr);
					LITTLE_BIG_SWAP(cmpdHdr.compSizeA);
					LITTLE_BIG_SWAP(cmpdHdr.decompSizeA);
					LITTLE_BIG_SWAP(cmpdHdr.compSizeB);
					LITTLE_BIG_SWAP(cmpdHdr.decompSizeB);
					decompSize = (cmpdHdr.decompSizeA & 0xFFFFFF) + (cmpdHdr.decompSizeB & 0xFFFFFF);
					compSize = (cmpdHdr.compSizeA & 0xFFFFFF) + (cmpdHdr.compSizeB & 0xFFFFFF);

					cmpdHdrv3_t *hdrp = (cmpdHdrv3_t *)rawData;
					pfxData = (BYTE *)&hdrp->texHdr;
					pfxDataSize = sizeof(hdrp->texHdr) + sizeof(hdrp->palInfoA) + sizeof(hdrp->palInfoB);
				}
				else if (ver == 2)
				{
					cmpdHdrv2_t cmpdHdr = *((cmpdHdrv2_t *)rawData);
					compHdrSize = sizeof(cmpdHdr);
					LITTLE_BIG_SWAP(cmpdHdr.compSize);
					LITTLE_BIG_SWAP(cmpdHdr.decompSize);
					decompSize = (cmpdHdr.decompSize & 0xFFFFFF);
					compSize = (cmpdHdr.compSize & 0xFFFFFF);

					cmpdHdrv2_t *hdrp = (cmpdHdrv2_t *)rawData;
					pfxData = (BYTE *)&hdrp->texHdr;
					pfxDataSize = sizeof(hdrp->texHdr);
				}
				else
				{
					cmpdHdrv1_t cmpdHdr = *((cmpdHdrv1_t *)rawData);
					compHdrSize = sizeof(cmpdHdr);
					LITTLE_BIG_SWAP(cmpdHdr.compSize);
					LITTLE_BIG_SWAP(cmpdHdr.decompSize);
					decompSize = (cmpdHdr.decompSize & 0xFFFFFF);
					compSize = (cmpdHdr.compSize & 0xFFFFFF);
				}
			}
			else
			{ //mp1/2, get the decompressed size out of the first 4 bytes (the rest is a zlib stream)
				decompSize = *((DWORD *)rawData);
				LITTLE_BIG_SWAP(decompSize);
				compSize = fi.size-compHdrSize;
			}

			BYTE *decompBuf = (BYTE *)rapi->Noesis_UnpooledAlloc(decompSize+pfxDataSize);
			if (pfxData && pfxDataSize > 0)
			{ //prepend texture info
				memcpy(decompBuf, pfxData, pfxDataSize);
			}
			if (decompSize != compSize)
			{
				int r;
				if (rawData[compHdrSize+0] == 0x78 && rawData[compHdrSize+1] == 0xDA)
				{ //metroid prime 1, zlib (assuming all of the files use the same compression level)
					r = rapi->Decomp_Inflate(rawData+compHdrSize, decompBuf+pfxDataSize, compSize, decompSize);
				}
				else
				{ //metroid prime 2/3, lzo
					r = rapi->Decomp_LZO2(rawData+compHdrSize, decompBuf+pfxDataSize, compSize, decompSize);
				}
				if (r >= 0)
				{ //success. free the compressed memory, change pointer to the decompressed buffer.
					rapi->Noesis_UnpooledFree(rawData);
					rawData = decompBuf;
					writeSize = decompSize+pfxDataSize;
				}
				else
				{
					rapi->Noesis_UnpooledFree(decompBuf);
				}
			}
			else
			{ //no decompression, but there is possibly a texture header
				memcpy(decompBuf+pfxDataSize, rawData+compHdrSize, decompSize);
				rapi->Noesis_UnpooledFree(rawData);
				rawData = decompBuf;
				writeSize = decompSize+pfxDataSize;
			}
		}

		//write it out
		rapi->LogOutput("Writing '%s'.\n", fname);
		rapi->Noesis_ExportArchiveFile(fname, rawData, writeSize);
		rapi->Noesis_UnpooledFree(rawData);
	}

	return true;
}

//when using the stream archive handler, you are responsible for managing the file handle yourself.
bool Model_PAK_Export(wchar_t *filename, __int64 len, bool justChecking, noeRAPI_t *rapi)
{
	if (len < sizeof(pakHdr_t))
	{
		return false;
	}
	FILE *f = NULL;
	_wfopen_s(&f, filename, L"rb");
	if (!f)
	{
		return false;
	}
	bool r = Model_PAK_ExportFromFile(f, len, justChecking, rapi);
	fclose(f);
	return r;
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	int fh = g_nfn->NPAPI_Register("Metroid Prime container", ".pak");
	if (fh < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_ExtractArcStream(fh, Model_PAK_Export);

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
