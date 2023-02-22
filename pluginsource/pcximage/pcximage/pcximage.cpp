//General requirements and/or suggestions for Noesis plugins:
//
// -Use 1-byte struct alignment for all shared structures. (plugin MSVC project file defaults everything to 1-byte-aligned)
// -Always clean up after yourself. Your plugin stays in memory the entire time Noesis is loaded, so you don't want to crap up the process heaps.
// -Try to use reliable type-checking, to ensure your plugin doesn't conflict with other file types and create false-positive situations.
// -Really try not to write crash-prone logic in your data check function! This could lead to Noesis crashing from trivial things like the user browsing files.
// -When using the rpg begin/end interface, always make your Vertex call last, as it's the function which triggers a push of the vertex with its current attributes.
// -!!!! Check the web site and documentation for updated suggestions/info! !!!!

#include "stdafx.h"

const char *g_pPluginName = "pcximage";
const char *g_pPluginDesc = "PCX image format handler, by Dick.";

typedef struct pcxHdr_s
{
	BYTE				id;
	BYTE				ver;
	BYTE				enc;
	BYTE				bitsPerPixel;

	WORD				xMin;
	WORD				yMin;
	WORD				xMax;
	WORD				yMax;

	WORD				hDPI;
	WORD				vDPI;

	BYTE				clrMap[48];
	BYTE				resv;
	BYTE				numPlanes;
	WORD				bytesPerLine;
	WORD				palInfo;
	WORD				hScreenSize;
	WORD				vScreenSize;

	BYTE				resvb[54];
} pcxHdr_t;

//see if something is valid pcx data
bool Image_PCX_Check(BYTE *fileBuffer, int bufferLen, noeRAPI_t *rapi)
{
	if (bufferLen < sizeof(pcxHdr_t))
	{
		return false;
	}
	pcxHdr_t *hdr = (pcxHdr_t *)fileBuffer;
	if (hdr->id != 10)
	{
		return false;
	}
	if (hdr->ver != 5 || hdr->enc != 1)
	{ //only bother supporting version 5 rle pcx files
		return false;
	}
	if (hdr->bitsPerPixel != 8)
	{ //not a supported bit depth
		return false;
	}
	if (hdr->numPlanes != 1 && hdr->numPlanes != 3 && hdr->numPlanes != 4)
	{ //not a supported format
		return false;
	}
	if (hdr->bytesPerLine <= 0 || hdr->bytesPerLine > bufferLen)
	{
		return false;
	}
	int w = (hdr->xMax - hdr->xMin)+1;
	int h = (hdr->yMax - hdr->yMin)+1;
	if (w <= 0 || h <= 0)
	{
		return false;
	}
	return true;
}

//load the pcx into the texture list
bool Image_PCX_Load(BYTE *fileBuffer, int bufferLen, CArrayList<noesisTex_t *> &noeTex, noeRAPI_t *rapi)
{
	pcxHdr_t *hdr = (pcxHdr_t *)fileBuffer;
	int w = (hdr->xMax - hdr->xMin)+1;
	int h = (hdr->yMax - hdr->yMin)+1;

	BYTE *pal = (hdr->numPlanes == 1 && bufferLen > 769) ? fileBuffer+bufferLen-769 : NULL;
	if (pal)
	{
		if (pal[0] != 12)
		{ //not valid 256-color palette data
			pal = NULL;
		}
		else
		{ //increment to palette entries
			pal++;
		}
	}

	BYTE *imgDst = (BYTE *)rapi->Noesis_UnpooledAlloc(w*h*4);
	BYTE *lineDst = (BYTE *)rapi->Noesis_UnpooledAlloc(hdr->bytesPerLine*hdr->numPlanes);
	BYTE *pixData = (BYTE *)(hdr+1);
	int totalp = 0;
	for (int i = 0; i < h; i++)
	{
		memset(lineDst, 0, hdr->bytesPerLine*hdr->numPlanes);
		BYTE *lineSrc = pixData + totalp;
		int dstp = 0;
		int linep = 0;
		while (dstp < hdr->bytesPerLine*hdr->numPlanes)
		{
			if (totalp+linep+(int)sizeof(pcxHdr_t) >= bufferLen)
			{ //decoding error
				break;
			}
			BYTE b = lineSrc[linep];
			linep++;
			if ((b & (1<<6)) && (b & (1<<7)))
			{
				BYTE numRep = (b & 63);
				BYTE pix = lineSrc[linep];
				linep++;
				for (int j = 0; j < numRep; j++)
				{
					lineDst[dstp] = pix;
					dstp++;
					if (dstp >= hdr->bytesPerLine*hdr->numPlanes)
					{
						break;
					}
				}
			}
			else
			{
				lineDst[dstp] = b;
				dstp++;
			}
		}
		totalp += linep;

		BYTE *imgLDst = imgDst + i*w*4;
		//copy the line into the main image buffer
		if (pal)
		{
			for (int j = 0; j < w; j++)
			{
				BYTE *dst = imgLDst + j*4;
				BYTE *src = lineDst + j;
				int palIdx = (int)src[0]*3;
				dst[0] = pal[palIdx+0];
				dst[1] = pal[palIdx+1];
				dst[2] = pal[palIdx+2];
				dst[3] = 255;
			}
		}
		else
		{
			for (int k = 0; k < 4; k++)
			{
				for (int j = 0; j < w; j++)
				{
					BYTE *dst = imgLDst + j*4;
					if (k >= hdr->numPlanes)
					{
						dst[k] = 255;
					}
					else
					{
						BYTE *src = lineDst + k*w + j;
						dst[k] = *src;
					}
				}
			}
		}
	}

	rapi->Noesis_UnpooledFree(lineDst);

	noesisTex_t *nt = rapi->Noesis_TextureAlloc("pcxout.png", w, h, imgDst, NOESISTEX_RGBA32);
	nt->shouldFreeData = true; //tell noesis that it should free this data itself
	noeTex.Append(nt);

	return true;
}

//export rgba pixel data to a 24-bit (8-bit, 3 planes) pcx
int Image_PCX_Save(char *fileName, BYTE *pix, int w, int h, noeRAPI_t *rapi)
{
	if (w > 65535 || h > 65535)
	{ //format limitation
		return -1;
	}
	RichBitStream bs;
	pcxHdr_t hdr;
	memset(&hdr, 0, sizeof(hdr));
	hdr.id = 10;
	hdr.ver = 5;
	hdr.enc = 1;
	hdr.bitsPerPixel = 8;
	hdr.xMin = 0;
	hdr.yMin = 0;
	hdr.xMax = w-1;
	hdr.yMax = h-1;
	hdr.hDPI = w;
	hdr.vDPI = h;
	hdr.numPlanes = 3;
	hdr.bytesPerLine = w;
	hdr.palInfo = 2;
	bs.WriteBytes(&hdr, sizeof(hdr));
	//do a fairly brain-dead rle encode
	for (int i = 0; i < h; i++)
	{
		for (int j = 0; j < 3; j++)
		{
			BYTE *lineSrc = pix + i*w*4 + j;
			for (int k = 0; k < w; k++)
			{
				BYTE pixRun = 0;
				int numPixRun = 0;
				while (k < w && numPixRun < 63)
				{
					BYTE pix = lineSrc[k*4];
					if (numPixRun <= 0)
					{
						pixRun = pix;
						numPixRun++;
					}
					else if (pix == pixRun)
					{
						numPixRun++;
					}
					else
					{
						break;
					}
					k++;
				}
				k--;
				BYTE rlen = numPixRun | (1<<6) | (1<<7);
				bs.WriteBytes(&rlen, 1);
				bs.WriteBytes(&pixRun, 1);
			}
		}
	}

	int l = bs.GetOffset();
	rapi->Noesis_WriteFile(fileName, bs.GetBuffer(), l);
	return l;
}

//called by Noesis to init the plugin
bool NPAPI_InitLocal(void)
{
	int th = g_nfn->NPAPI_Register("PCX Image", ".pcx");
	if (th < 0)
	{
		return false;
	}

	//set the data handlers for this format
	g_nfn->NPAPI_SetTypeHandler_TypeCheck(th, Image_PCX_Check);
	g_nfn->NPAPI_SetTypeHandler_LoadRGBA(th, Image_PCX_Load);
	g_nfn->NPAPI_SetTypeHandler_WriteRGBA(th, Image_PCX_Save);

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
