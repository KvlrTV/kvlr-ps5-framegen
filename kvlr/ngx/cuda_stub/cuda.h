// Minimal stand-in for CUDA's cuda.h: only the handle types NVIDIA's Optical Flow headers use. The real driver
// (nvcuda.dll) is loaded by PyTorch at run time; no CUDA toolkit is needed to build kvlr_ngx.dll.
#pragma once
typedef struct CUctx_st* CUcontext;
typedef struct CUstream_st* CUstream;
typedef struct CUarray_st* CUarray;
typedef unsigned long long CUdeviceptr;
