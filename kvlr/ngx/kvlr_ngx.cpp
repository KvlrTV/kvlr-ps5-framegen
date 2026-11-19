// KVLR edition: a small native helper that runs NVIDIA DLSS (NGX, Direct3D 12) for the Python pipeline.
//
// Stage 1 (this file): DLSS Super Resolution on frames handed over in CPU memory (RGBA8 in, RGBA8 out), to prove
// DLSS SR on captured video. Later stages share textures with the CUDA pipeline instead of copying through the CPU,
// and add DLSS Frame Generation.
//
// Our code (MIT, like the rest of the fork). It is built against NVIDIA's DLSS SDK headers and nvsdk_ngx_d.lib, which
// are NOT in this repository (NVIDIA RTX SDKs licence): kvlr/ngx/build_ngx.py takes them from
// ..\kvlr-ps5-framegen-inputs\dlss-sdk. This software contains source code provided by NVIDIA Corporation only in
// the sense that it includes NVIDIA's SDK headers at build time.
//
// Captured video has no depth, no engine motion vectors and no camera jitter, so DLSS SR gets a constant depth, zero
// motion vectors (or optical-flow ones in a later stage) and no jitter; Reset is set on scene cuts.

#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <string>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "nvsdk_ngx.h"
#include "nvsdk_ngx_helpers.h"
#include "nvsdk_ngx_defs_dlssg.h"

using Microsoft::WRL::ComPtr;

#define KVLR_API extern "C" __declspec(dllexport)

namespace {

std::string g_err;
std::recursive_mutex g_lock;  // one command list and queue for every caller
ComPtr<ID3D12Device> g_dev;
ComPtr<ID3D12CommandQueue> g_queue;
ComPtr<ID3D12CommandAllocator> g_alloc;
ComPtr<ID3D12GraphicsCommandList> g_list;
ComPtr<ID3D12Fence> g_fence;
HANDLE g_event = nullptr;
UINT64 g_fenceValue = 0;
ComPtr<ID3D12QueryHeap> g_queries;
ComPtr<ID3D12Resource> g_queryReadback;
UINT64 g_tsFreq = 1;
NVSDK_NGX_Parameter* g_params = nullptr;
bool g_ngx = false;
char g_adapterName[256] = {};

struct Sr {
    NVSDK_NGX_Handle* handle = nullptr;
    unsigned inW = 0, inH = 0, outW = 0, outH = 0;
    ComPtr<ID3D12Resource> color, output, mv, depth;
    ComPtr<ID3D12Resource> upload, readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT upFoot{}, rbFoot{};
} g_sr;

bool fail(const char* what, long code = 0) {
    char buf[512];
    snprintf(buf, sizeof buf, "%s (0x%08lx)", what, (unsigned long)code);
    g_err = buf;
    return false;
}

bool wait_gpu() {
    g_queue->Signal(g_fence.Get(), ++g_fenceValue);
    if (g_fence->GetCompletedValue() < g_fenceValue) {
        g_fence->SetEventOnCompletion(g_fenceValue, g_event);
        WaitForSingleObject(g_event, 10000);
    }
    return true;
}

ComPtr<ID3D12Resource> texture(unsigned w, unsigned h, DXGI_FORMAT fmt, bool uav, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES hp{D3D12_HEAP_TYPE_DEFAULT};
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w; d.Height = h; d.DepthOrArraySize = 1; d.MipLevels = 1; d.Format = fmt;
    d.SampleDesc.Count = 1;
    d.Flags = uav ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
    ComPtr<ID3D12Resource> r;
    if (FAILED(g_dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r))))
        return nullptr;
    return r;
}

ComPtr<ID3D12Resource> buffer(UINT64 size, D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES hp{type};
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = size; d.Height = 1; d.DepthOrArraySize = 1; d.MipLevels = 1; d.Format = DXGI_FORMAT_UNKNOWN;
    d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> r;
    if (FAILED(g_dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r))))
        return nullptr;
    return r;
}

void barrier(ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER br{};
    br.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    br.Transition.pResource = r; br.Transition.StateBefore = a; br.Transition.StateAfter = b;
    br.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    g_list->ResourceBarrier(1, &br);
}

void release_sr() {
    if (g_sr.handle) { NVSDK_NGX_D3D12_ReleaseFeature(g_sr.handle); g_sr.handle = nullptr; }
    g_sr = Sr{};
}

}  // namespace

KVLR_API const char* kvlr_ngx_error() { return g_err.c_str(); }
KVLR_API const char* kvlr_ngx_adapter() { return g_adapterName; }

// Starts Direct3D 12 on the fastest NVIDIA adapter and NGX, with the DLSS DLLs looked up in `dll_dir`
// (nvngx_dlss.dll, nvngx_dlssg.dll). Returns 1 on success.
KVLR_API int kvlr_ngx_init(const wchar_t* dll_dir, const wchar_t* data_dir) {
    ComPtr<IDXGIFactory6> fac;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&fac)))) return fail("CreateDXGIFactory2");
    ComPtr<IDXGIAdapter1> ad;
    for (UINT i = 0; fac->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&ad)) !=
                     DXGI_ERROR_NOT_FOUND; ++i) {
        DXGI_ADAPTER_DESC1 d; ad->GetDesc1(&d);
        if (d.VendorId == 0x10DE) { WideCharToMultiByte(CP_UTF8, 0, d.Description, -1, g_adapterName, 255, 0, 0); break; }
        ad.Reset();
    }
    if (!ad) return fail("no NVIDIA graphics card found");
    HRESULT hr = D3D12CreateDevice(ad.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&g_dev));
    if (FAILED(hr)) return fail("D3D12CreateDevice", hr);
    D3D12_COMMAND_QUEUE_DESC qd{D3D12_COMMAND_LIST_TYPE_DIRECT};
    g_dev->CreateCommandQueue(&qd, IID_PPV_ARGS(&g_queue));
    g_dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&g_alloc));
    g_dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, g_alloc.Get(), nullptr, IID_PPV_ARGS(&g_list));
    g_list->Close();
    g_dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&g_fence));
    g_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    D3D12_QUERY_HEAP_DESC qh{D3D12_QUERY_HEAP_TYPE_TIMESTAMP, 2};
    g_dev->CreateQueryHeap(&qh, IID_PPV_ARGS(&g_queries));
    g_queryReadback = buffer(16, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    g_queue->GetTimestampFrequency(&g_tsFreq);

    const wchar_t* paths[] = {dll_dir};
    NVSDK_NGX_FeatureCommonInfo info{};
    info.PathListInfo.Path = paths;
    info.PathListInfo.Length = 1;
    NVSDK_NGX_Result r = NVSDK_NGX_D3D12_Init_with_ProjectID(
        "5b7c3f0e-6d2a-4f53-9a51-4b56c3d1e7aa", NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", data_dir, g_dev.Get(), &info);
    if (NVSDK_NGX_FAILED(r)) return fail("NGX init", r);
    g_ngx = true;
    r = NVSDK_NGX_D3D12_GetCapabilityParameters(&g_params);
    if (NVSDK_NGX_FAILED(r)) return fail("NGX capability parameters", r);
    int ok = 0;
    g_params->Get(NVSDK_NGX_Parameter_SuperSampling_Available, &ok);
    if (!ok) {
        int why = 0; g_params->Get(NVSDK_NGX_Parameter_SuperSampling_FeatureInitResult, &why);
        return fail("DLSS Super Resolution isn't available on this PC", why);
    }
    return 1;
}

// What NGX says about DLSS Frame Generation here: 1 available (2x), 2 available with multi-frame (up to 4x).
KVLR_API int kvlr_ngx_fg_support() {
    if (!g_params) return 0;
    int ok = 0, mfg = 0;
    g_params->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &ok);
    g_params->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax, &mfg);
    return ok ? (mfg > 1 ? 2 : 1) : 0;
}

// Creates DLSS SR for in_w x in_h -> out_w x out_h. preset: NGX render preset (0 default, 11 K, 12 L, 13 M).
KVLR_API int kvlr_sr_create(unsigned in_w, unsigned in_h, unsigned out_w, unsigned out_h, int preset) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (!g_ngx) return fail("NGX not started");
    release_sr();
    g_sr.inW = in_w; g_sr.inH = in_h; g_sr.outW = out_w; g_sr.outH = out_h;
    g_sr.color = texture(in_w, in_h, DXGI_FORMAT_R8G8B8A8_UNORM, false, D3D12_RESOURCE_STATE_COPY_DEST);
    g_sr.output = texture(out_w, out_h, DXGI_FORMAT_R8G8B8A8_UNORM, true, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    g_sr.mv = texture(in_w, in_h, DXGI_FORMAT_R16G16_FLOAT, false, D3D12_RESOURCE_STATE_COPY_DEST);
    g_sr.depth = texture(in_w, in_h, DXGI_FORMAT_R32_FLOAT, false, D3D12_RESOURCE_STATE_COPY_DEST);
    if (!g_sr.color || !g_sr.output || !g_sr.mv || !g_sr.depth) return fail("couldn't make the DLSS textures");

    UINT64 upSize = 0, rbSize = 0;
    D3D12_RESOURCE_DESC cd = g_sr.color->GetDesc(), od = g_sr.output->GetDesc();
    g_dev->GetCopyableFootprints(&cd, 0, 1, 0, &g_sr.upFoot, nullptr, nullptr, &upSize);
    g_dev->GetCopyableFootprints(&od, 0, 1, 0, &g_sr.rbFoot, nullptr, nullptr, &rbSize);
    // one upload buffer, also used once to zero the motion vectors (4 bytes/px) and depth (4 bytes/px)
    g_sr.upload = buffer(upSize, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    g_sr.readback = buffer(rbSize, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    if (!g_sr.upload || !g_sr.readback) return fail("couldn't make the copy buffers");

    // zero motion, constant depth (0): written once through the upload buffer
    void* p = nullptr; g_sr.upload->Map(0, nullptr, &p); memset(p, 0, (size_t)upSize); g_sr.upload->Unmap(0, nullptr);
    g_alloc->Reset(); g_list->Reset(g_alloc.Get(), nullptr);
    for (ID3D12Resource* r : {g_sr.mv.Get(), g_sr.depth.Get()}) {
        D3D12_RESOURCE_DESC rd = r->GetDesc();
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT f; g_dev->GetCopyableFootprints(&rd, 0, 1, 0, &f, nullptr, nullptr, nullptr);
        D3D12_TEXTURE_COPY_LOCATION dst{r, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION src{g_sr.upload.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; src.PlacedFootprint = f;
        g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        barrier(r, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }

    float ratio = (float)out_w / in_w;
    NVSDK_NGX_PerfQuality_Value q = ratio >= 2.9f ? NVSDK_NGX_PerfQuality_Value_UltraPerformance
                                  : ratio >= 1.9f ? NVSDK_NGX_PerfQuality_Value_MaxPerf
                                  : ratio >= 1.65f ? NVSDK_NGX_PerfQuality_Value_Balanced
                                  : ratio >= 1.4f ? NVSDK_NGX_PerfQuality_Value_MaxQuality
                                  : NVSDK_NGX_PerfQuality_Value_DLAA;
    for (const char* k : {NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA, NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality,
                          NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced, NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance,
                          NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance})
        g_params->Set(k, (unsigned)preset);
    NVSDK_NGX_DLSS_Create_Params cp{};
    cp.Feature.InWidth = in_w; cp.Feature.InHeight = in_h;
    cp.Feature.InTargetWidth = out_w; cp.Feature.InTargetHeight = out_h;
    cp.Feature.InPerfQualityValue = q;
    cp.InFeatureCreateFlags = NVSDK_NGX_DLSS_Feature_Flags_MVLowRes | NVSDK_NGX_DLSS_Feature_Flags_AutoExposure;
    NVSDK_NGX_Result r = NGX_D3D12_CREATE_DLSS_EXT(g_list.Get(), 1, 1, &g_sr.handle, g_params, &cp);
    g_list->Close();
    ID3D12CommandList* lists[] = {g_list.Get()};
    g_queue->ExecuteCommandLists(1, lists);
    wait_gpu();
    if (NVSDK_NGX_FAILED(r)) return fail("creating DLSS Super Resolution", r);
    return 1;
}

// Upscales one RGBA8 frame (in_w*in_h*4 bytes, tightly packed) into `out` (out_w*out_h*4 bytes). reset: 1 on the
// first frame and on scene cuts. gpu_ms (optional) gets the DLSS evaluation time on the graphics card.
KVLR_API int kvlr_sr_upscale(const unsigned char* in, unsigned char* out, int reset, float* gpu_ms) {
    if (!g_sr.handle) return fail("DLSS SR not created");
    unsigned char* p = nullptr;
    g_sr.upload->Map(0, nullptr, (void**)&p);
    for (unsigned y = 0; y < g_sr.inH; ++y)
        memcpy(p + g_sr.upFoot.Offset + (size_t)y * g_sr.upFoot.Footprint.RowPitch, in + (size_t)y * g_sr.inW * 4, g_sr.inW * 4);
    g_sr.upload->Unmap(0, nullptr);

    g_alloc->Reset(); g_list->Reset(g_alloc.Get(), nullptr);
    D3D12_TEXTURE_COPY_LOCATION dst{g_sr.color.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION src{g_sr.upload.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; src.PlacedFootprint = g_sr.upFoot;
    g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier(g_sr.color.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    NVSDK_NGX_D3D12_DLSS_Eval_Params ep{};
    ep.Feature.pInColor = g_sr.color.Get();
    ep.Feature.pInOutput = g_sr.output.Get();
    ep.pInDepth = g_sr.depth.Get();
    ep.pInMotionVectors = g_sr.mv.Get();
    ep.InRenderSubrectDimensions = {g_sr.inW, g_sr.inH};
    ep.InReset = reset;
    ep.InMVScaleX = 1.0f; ep.InMVScaleY = 1.0f;
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
    NVSDK_NGX_Result r = NGX_D3D12_EVALUATE_DLSS_EXT(g_list.Get(), g_sr.handle, g_params, &ep);
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
    g_list->ResolveQueryData(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, g_queryReadback.Get(), 0);

    barrier(g_sr.color.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
    barrier(g_sr.output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION rdst{g_sr.readback.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; rdst.PlacedFootprint = g_sr.rbFoot;
    D3D12_TEXTURE_COPY_LOCATION rsrc{g_sr.output.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; rsrc.SubresourceIndex = 0;
    g_list->CopyTextureRegion(&rdst, 0, 0, 0, &rsrc, nullptr);
    barrier(g_sr.output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    g_list->Close();
    ID3D12CommandList* lists[] = {g_list.Get()};
    g_queue->ExecuteCommandLists(1, lists);
    wait_gpu();
    if (NVSDK_NGX_FAILED(r)) return fail("DLSS evaluate", r);

    g_sr.readback->Map(0, nullptr, (void**)&p);
    for (unsigned y = 0; y < g_sr.outH; ++y)
        memcpy(out + (size_t)y * g_sr.outW * 4, p + g_sr.rbFoot.Offset + (size_t)y * g_sr.rbFoot.Footprint.RowPitch, g_sr.outW * 4);
    g_sr.readback->Unmap(0, nullptr);
    if (gpu_ms) {
        UINT64* ts = nullptr; g_queryReadback->Map(0, nullptr, (void**)&ts);
        *gpu_ms = (float)((ts[1] - ts[0]) * 1000.0 / g_tsFreq);
        g_queryReadback->Unmap(0, nullptr);
    }
    return 1;
}

// ---- stage 2: frames shared with CUDA (no copies through the CPU) --------------------------------------------
// Two buffers live in shared graphics memory: the input (RGBA8 rows, in_pitch bytes apart) and the output (packed
// 10-bit RGB, R in the low bits, out_pitch bytes apart: the layout of GL's RGB10_A2 / NVIDIA VSR's output). The caller
// imports both into CUDA from the NT handles (cudaImportExternalMemory, D3D12 resource), writes the input, calls
// kvlr_sr_shared_eval (which waits for the graphics card), and reads the output.
namespace {
struct Shared {
    ComPtr<ID3D12Resource> inBuf, outBuf, mvBuf;
    HANDLE inHandle = nullptr, outHandle = nullptr, mvHandle = nullptr;
    UINT64 inSize = 0, outSize = 0, mvSize = 0;
    UINT inPitch = 0, outPitch = 0, mvPitch = 0;
    ComPtr<ID3D12Resource> outTex;  // DLSS output in R10G10B10A2 (the stage-1 RGBA8 output is left unused)
} g_sh;

ComPtr<ID3D12Resource> shared_buffer(UINT64 size, HANDLE* handle, UINT64* alloc) {
    D3D12_HEAP_PROPERTIES hp{D3D12_HEAP_TYPE_DEFAULT};
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = size; d.Height = 1; d.DepthOrArraySize = 1; d.MipLevels = 1; d.Format = DXGI_FORMAT_UNKNOWN;
    d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> r;
    if (FAILED(g_dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_SHARED, &d, D3D12_RESOURCE_STATE_COMMON, nullptr,
                                              IID_PPV_ARGS(&r))))
        return nullptr;
    if (FAILED(g_dev->CreateSharedHandle(r.Get(), nullptr, GENERIC_ALL, nullptr, handle))) return nullptr;
    *alloc = g_dev->GetResourceAllocationInfo(0, 1, &d).SizeInBytes;
    return r;
}

void release_shared() {
    if (g_sh.inHandle) CloseHandle(g_sh.inHandle);
    if (g_sh.outHandle) CloseHandle(g_sh.outHandle);
    if (g_sh.mvHandle) CloseHandle(g_sh.mvHandle);
    g_sh = Shared{};
}
}  // namespace

// Creates DLSS SR in_w x in_h -> out_w x out_h with shared buffers. Fills the NT handles, their allocation sizes and
// row pitches. Handles stay owned here (closed on the next create or shutdown); CUDA keeps its own reference.
KVLR_API int kvlr_sr_shared_create(unsigned in_w, unsigned in_h, unsigned out_w, unsigned out_h, int preset,
                                   void** in_handle, unsigned long long* in_size, unsigned* in_pitch,
                                   void** out_handle, unsigned long long* out_size, unsigned* out_pitch) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    release_shared();
    if (!kvlr_sr_create(in_w, in_h, out_w, out_h, preset)) return 0;
    g_sh.outTex = texture(out_w, out_h, DXGI_FORMAT_R10G10B10A2_UNORM, true, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    if (!g_sh.outTex) return fail("couldn't make the DLSS output texture");
    g_sh.inPitch = (in_w * 4 + 255) & ~255u;
    g_sh.outPitch = (out_w * 4 + 255) & ~255u;
    g_sh.inBuf = shared_buffer((UINT64)g_sh.inPitch * in_h, &g_sh.inHandle, &g_sh.inSize);
    g_sh.outBuf = shared_buffer((UINT64)g_sh.outPitch * out_h, &g_sh.outHandle, &g_sh.outSize);
    if (!g_sh.inBuf || !g_sh.outBuf) return fail("couldn't make the shared buffers");
    *in_handle = g_sh.inHandle; *in_size = g_sh.inSize; *in_pitch = g_sh.inPitch;
    *out_handle = g_sh.outHandle; *out_size = g_sh.outSize; *out_pitch = g_sh.outPitch;
    return 1;
}

// The shared motion-vector buffer (R16G16_FLOAT rows, in_w x in_h, mv_pitch bytes apart): pixels from the current frame
// back to the previous one, in input pixels (DLSS's convention). Made on first use.
KVLR_API int kvlr_sr_shared_mv(void** handle, unsigned long long* size, unsigned* pitch) {
    if (!g_sr.handle) return fail("DLSS SR not created");
    if (!g_sh.mvBuf) {
        g_sh.mvPitch = (g_sr.inW * 4 + 255) & ~255u;
        g_sh.mvBuf = shared_buffer((UINT64)g_sh.mvPitch * g_sr.inH, &g_sh.mvHandle, &g_sh.mvSize);
        if (!g_sh.mvBuf) return fail("couldn't make the motion-vector buffer");
    }
    *handle = g_sh.mvHandle; *size = g_sh.mvSize; *pitch = g_sh.mvPitch;
    return 1;
}

// One frame: the shared input (and motion vectors, if use_mv) -> DLSS -> the shared output. Waits for the graphics
// card before returning.
KVLR_API int kvlr_sr_shared_eval_mv(int reset, int use_mv, float* gpu_ms);
KVLR_API int kvlr_sr_shared_eval(int reset, float* gpu_ms) { return kvlr_sr_shared_eval_mv(reset, 0, gpu_ms); }
KVLR_API int kvlr_sr_shared_eval_mv(int reset, int use_mv, float* gpu_ms) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (!g_sr.handle || !g_sh.inBuf) return fail("DLSS SR (shared) not created");
    g_alloc->Reset(); g_list->Reset(g_alloc.Get(), nullptr);
    D3D12_TEXTURE_COPY_LOCATION dst{g_sr.color.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION src{g_sh.inBuf.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    src.PlacedFootprint.Offset = 0;
    src.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, g_sr.inW, g_sr.inH, 1, g_sh.inPitch};
    g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier(g_sr.color.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    if (use_mv && g_sh.mvBuf) {
        barrier(g_sr.mv.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION mdst{g_sr.mv.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; mdst.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION msrc{g_sh.mvBuf.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
        msrc.PlacedFootprint.Offset = 0;
        msrc.PlacedFootprint.Footprint = {DXGI_FORMAT_R16G16_FLOAT, g_sr.inW, g_sr.inH, 1, g_sh.mvPitch};
        g_list->CopyTextureRegion(&mdst, 0, 0, 0, &msrc, nullptr);
        barrier(g_sr.mv.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }

    NVSDK_NGX_D3D12_DLSS_Eval_Params ep{};
    ep.Feature.pInColor = g_sr.color.Get();
    ep.Feature.pInOutput = g_sh.outTex.Get();
    ep.pInDepth = g_sr.depth.Get();
    ep.pInMotionVectors = g_sr.mv.Get();
    ep.InRenderSubrectDimensions = {g_sr.inW, g_sr.inH};
    ep.InReset = reset;
    ep.InMVScaleX = 1.0f; ep.InMVScaleY = 1.0f;
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
    NVSDK_NGX_Result r = NGX_D3D12_EVALUATE_DLSS_EXT(g_list.Get(), g_sr.handle, g_params, &ep);
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
    g_list->ResolveQueryData(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, g_queryReadback.Get(), 0);

    barrier(g_sr.color.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
    barrier(g_sh.outTex.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION odst{g_sh.outBuf.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    odst.PlacedFootprint.Offset = 0;
    odst.PlacedFootprint.Footprint = {DXGI_FORMAT_R10G10B10A2_UNORM, g_sr.outW, g_sr.outH, 1, g_sh.outPitch};
    D3D12_TEXTURE_COPY_LOCATION osrc{g_sh.outTex.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; osrc.SubresourceIndex = 0;
    g_list->CopyTextureRegion(&odst, 0, 0, 0, &osrc, nullptr);
    barrier(g_sh.outTex.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    g_list->Close();
    ID3D12CommandList* lists[] = {g_list.Get()};
    g_queue->ExecuteCommandLists(1, lists);
    wait_gpu();
    if (NVSDK_NGX_FAILED(r)) return fail("DLSS evaluate", r);
    if (gpu_ms) {
        UINT64* ts = nullptr; g_queryReadback->Map(0, nullptr, (void**)&ts);
        *gpu_ms = (float)((ts[1] - ts[0]) * 1000.0 / g_tsFreq);
        g_queryReadback->Unmap(0, nullptr);
    }
    return 1;
}

// ---- NVIDIA Optical Flow (hardware), on CUDA: motion for DLSS SR ---------------------------------------------
// nvofapi64.dll ships with the driver; the BSD-licensed headers come from NVIDIA's Optical Flow SDK
// (..\kvlr-ps5-framegen-inputs\nvof). Runs on the caller's CUDA context and stream (PyTorch's).
#include "nvOpticalFlowCommon.h"
#include "nvOpticalFlowCuda.h"

namespace {
NV_OF_CUDA_API_FUNCTION_LIST g_of{};
struct Flow { NvOFHandle h = nullptr; NvOFGPUBufferHandle in[2] = {}, out = nullptr; };
Flow g_flows[4];
void destroy_flow(Flow& f) {
    if (!f.h) return;
    for (auto& b : f.in) if (b) { g_of.nvOFDestroyGPUBufferCuda(b); b = nullptr; }
    if (f.out) { g_of.nvOFDestroyGPUBufferCuda(f.out); f.out = nullptr; }
    g_of.nvOFDestroy(f.h); f.h = nullptr;
}
}

// Creates hardware optical flow for w x h grayscale frames (grid: 1, 2 or 4 pixels per vector; perf: 5 slow, 10
// medium, 20 fast). Fills the CUDA device pointers and row strides of the two input buffers and the output (S10.5
// int16 x,y per grid cell, out_w x out_h).
KVLR_API int kvlr_of_create2(int id, unsigned w, unsigned h, unsigned grid, int perf, void* stream,
                            unsigned long long* in0, unsigned long long* in1, unsigned* in_stride,
                            unsigned long long* out, unsigned* out_stride, unsigned* out_w, unsigned* out_h) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (id < 0 || id > 3) return fail("bad optical flow id");
    Flow& f = g_flows[id];
    destroy_flow(f);
    HMODULE ofdll = LoadLibraryW(L"nvofapi64.dll");
    HMODULE cuda = GetModuleHandleW(L"nvcuda.dll");
    if (!ofdll || !cuda) return fail("NVIDIA Optical Flow (nvofapi64.dll) or CUDA isn't loaded");
    auto create = (NV_OF_STATUS(NVOFAPI*)(uint32_t, NV_OF_CUDA_API_FUNCTION_LIST*))GetProcAddress(ofdll, "NvOFAPICreateInstanceCuda");
    auto getctx = (int(__stdcall*)(CUcontext*))GetProcAddress(cuda, "cuCtxGetCurrent");
    if (!create || !getctx) return fail("NVIDIA Optical Flow entry points missing");
    CUcontext ctx = nullptr; getctx(&ctx);
    if (!ctx) return fail("no current CUDA context");
    NV_OF_STATUS st = create(NV_OF_API_VERSION, &g_of);
    if (st) return fail("NvOFAPICreateInstanceCuda", st);
    if ((st = g_of.nvCreateOpticalFlowCuda(ctx, &f.h))) return fail("nvCreateOpticalFlowCuda", st);
    g_of.nvOFSetIOCudaStreams(f.h, (CUstream)stream, (CUstream)stream);
    NV_OF_INIT_PARAMS ip{};
    ip.width = w; ip.height = h;
    ip.outGridSize = (NV_OF_OUTPUT_VECTOR_GRID_SIZE)grid;
    ip.hintGridSize = NV_OF_HINT_VECTOR_GRID_SIZE_UNDEFINED;
    ip.mode = NV_OF_MODE_OPTICALFLOW;
    ip.perfLevel = (NV_OF_PERF_LEVEL)perf;
    ip.disparityRange = NV_OF_STEREO_DISPARITY_RANGE_UNDEFINED;
    if ((st = g_of.nvOFInit(f.h, &ip))) return fail("nvOFInit", st);
    NV_OF_BUFFER_DESCRIPTOR bd{w, h, NV_OF_BUFFER_USAGE_INPUT, NV_OF_BUFFER_FORMAT_GRAYSCALE8};
    for (int i = 0; i < 2; ++i)
        if ((st = g_of.nvOFCreateGPUBufferCuda(f.h, &bd, NV_OF_CUDA_BUFFER_TYPE_CUDEVICEPTR, &f.in[i])))
            return fail("nvOFCreateGPUBufferCuda (input)", st);
    unsigned ow = (w + grid - 1) / grid, oh = (h + grid - 1) / grid;
    NV_OF_BUFFER_DESCRIPTOR od{ow, oh, NV_OF_BUFFER_USAGE_OUTPUT, NV_OF_BUFFER_FORMAT_SHORT2};
    if ((st = g_of.nvOFCreateGPUBufferCuda(f.h, &od, NV_OF_CUDA_BUFFER_TYPE_CUDEVICEPTR, &f.out)))
        return fail("nvOFCreateGPUBufferCuda (output)", st);
    NV_OF_CUDA_BUFFER_STRIDE_INFO si{};
    g_of.nvOFGPUBufferGetStrideInfo(f.in[0], &si); *in_stride = si.strideInfo[0].strideXInBytes;
    g_of.nvOFGPUBufferGetStrideInfo(f.out, &si); *out_stride = si.strideInfo[0].strideXInBytes;
    *in0 = g_of.nvOFGPUBufferGetCUdeviceptr(f.in[0]);
    *in1 = g_of.nvOFGPUBufferGetCUdeviceptr(f.in[1]);
    *out = g_of.nvOFGPUBufferGetCUdeviceptr(f.out);
    *out_w = ow; *out_h = oh;
    return 1;
}

// Flow from input buffer `cur` (this frame) to the other one (the previous frame), queued on the stream.
KVLR_API int kvlr_of_run2(int id, int cur) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (id < 0 || id > 3 || !g_flows[id].h) return fail("optical flow not created");
    Flow& f = g_flows[id];
    NV_OF_EXECUTE_INPUT_PARAMS in{};
    in.inputFrame = f.in[cur & 1]; in.referenceFrame = f.in[(cur + 1) & 1];
    NV_OF_EXECUTE_OUTPUT_PARAMS out{};
    out.outputBuffer = f.out;
    NV_OF_STATUS st = g_of.nvOFExecute(f.h, &in, &out);
    return st ? fail("nvOFExecute", st) : 1;
}

// The first instance under the stage-2 names (DLSS SR's).
KVLR_API int kvlr_of_create(unsigned w, unsigned h, unsigned grid, int perf, void* stream,
                            unsigned long long* in0, unsigned long long* in1, unsigned* in_stride,
                            unsigned long long* out, unsigned* out_stride, unsigned* out_w, unsigned* out_h) {
    return kvlr_of_create2(0, w, h, grid, perf, stream, in0, in1, in_stride, out, out_stride, out_w, out_h);
}
KVLR_API int kvlr_of_run(int cur) { return kvlr_of_run2(0, cur); }

KVLR_API void kvlr_of_destroy() {
    for (auto& f : g_flows) destroy_flow(f);
}

// ---- DLSS Frame Generation (NGX DLSS-G) on frames shared with CUDA -------------------------------------------
// Inputs per real frame: the frame (RGBA8), motion vectors (R16G16_FLOAT, pixels from this frame back to the
// previous one: the same optical flow as DLSS SR uses) and a constant depth; camera matrices are identity (captured
// video has no camera data; the motion vectors carry all of it). Output: one generated RGBA8 frame per call, frame
// `index` of `count` between the previous real frame and this one (count 1 = 2x, 3 = 4x).
#include "nvsdk_ngx_helpers_dlssg.h"
#include "nvsdk_ngx_helpers_dlssg_d3d.h"
#include "nvsdk_ngx_params_dlssg.h"

namespace {
struct Fg {
    NVSDK_NGX_Handle* handle = nullptr;
    unsigned w = 0, h = 0;
    ComPtr<ID3D12Resource> back, depth, mv, out;
    ComPtr<ID3D12Resource> inBuf, mvBuf, outBuf, depthBuf;
    HANDLE inH = nullptr, mvH = nullptr, outH = nullptr, depthH = nullptr;
    UINT64 inSize = 0, mvSize = 0, outSize = 0, depthSize = 0;
    UINT pitch = 0;  // rows of all three buffers (4 bytes a pixel)
} g_fg;

void release_fg() {
    if (g_fg.handle) { NVSDK_NGX_D3D12_ReleaseFeature(g_fg.handle); g_fg.handle = nullptr; }
    for (HANDLE hh : {g_fg.inH, g_fg.mvH, g_fg.outH, g_fg.depthH}) if (hh) CloseHandle(hh);
    g_fg = Fg{};
}
}

// Creates DLSS-G for w x h frames with three shared buffers (frame in, motion in, generated frame out), all with
// `pitch`-byte rows. Returns their NT handles and allocation sizes.
KVLR_API int kvlr_fg_create2(unsigned w, unsigned h, int lite, void** in_h, unsigned long long* in_size, void** mv_h,
                             unsigned long long* mv_size, void** out_h, unsigned long long* out_size, void** depth_h,
                             unsigned long long* depth_size, unsigned* pitch);
KVLR_API int kvlr_fg_create(unsigned w, unsigned h, void** in_h, unsigned long long* in_size, void** mv_h,
                            unsigned long long* mv_size, void** out_h, unsigned long long* out_size, unsigned* pitch) {
    void* dh = nullptr; unsigned long long ds = 0;
    return kvlr_fg_create2(w, h, 0, in_h, in_size, mv_h, mv_size, out_h, out_size, &dh, &ds, pitch);
}
// lite: DLSS-G's lighter "candidate blending" (set at creation). depth: a shared R32_FLOAT buffer (rows `pitch` bytes
// apart) for estimated depth, copied in with each new real frame when kvlr_fg_eval2's use_depth is set.
KVLR_API int kvlr_fg_create2(unsigned w, unsigned h, int lite, void** in_h, unsigned long long* in_size, void** mv_h,
                             unsigned long long* mv_size, void** out_h, unsigned long long* out_size, void** depth_h,
                             unsigned long long* depth_size, unsigned* pitch) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (!g_ngx) return fail("NGX not started");
    int ok = 0;
    g_params->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &ok);
    if (!ok) { int why = 0; g_params->Get(NVSDK_NGX_Parameter_FrameGeneration_FeatureInitResult, &why);
               return fail("DLSS Frame Generation isn't available on this PC", why); }
    wait_gpu();
    release_fg();
    g_fg.w = w; g_fg.h = h;
    g_fg.back = texture(w, h, DXGI_FORMAT_R8G8B8A8_UNORM, false, D3D12_RESOURCE_STATE_COPY_DEST);
    g_fg.depth = texture(w, h, DXGI_FORMAT_R32_FLOAT, false, D3D12_RESOURCE_STATE_COPY_DEST);
    g_fg.mv = texture(w, h, DXGI_FORMAT_R16G16_FLOAT, false, D3D12_RESOURCE_STATE_COPY_DEST);
    g_fg.out = texture(w, h, DXGI_FORMAT_R8G8B8A8_UNORM, true, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    if (!g_fg.back || !g_fg.depth || !g_fg.mv || !g_fg.out) return fail("couldn't make the frame generation textures");
    g_fg.pitch = (w * 4 + 255) & ~255u;
    UINT64 sz = (UINT64)g_fg.pitch * h;
    g_fg.inBuf = shared_buffer(sz, &g_fg.inH, &g_fg.inSize);
    g_fg.mvBuf = shared_buffer(sz, &g_fg.mvH, &g_fg.mvSize);
    g_fg.outBuf = shared_buffer(sz, &g_fg.outH, &g_fg.outSize);
    g_fg.depthBuf = shared_buffer(sz, &g_fg.depthH, &g_fg.depthSize);
    if (!g_fg.inBuf || !g_fg.mvBuf || !g_fg.outBuf || !g_fg.depthBuf) return fail("couldn't make the frame generation buffers");

    // depth: a constant 0 (one far plane), written once through a zeroed upload buffer
    ComPtr<ID3D12Resource> zero = buffer(sz, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    void* p = nullptr; zero->Map(0, nullptr, &p); memset(p, 0, (size_t)sz); zero->Unmap(0, nullptr);
    g_alloc->Reset(); g_list->Reset(g_alloc.Get(), nullptr);
    D3D12_TEXTURE_COPY_LOCATION dst{g_fg.depth.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION src{zero.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    src.PlacedFootprint.Offset = 0;
    src.PlacedFootprint.Footprint = {DXGI_FORMAT_R32_FLOAT, w, h, 1, g_fg.pitch};
    g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier(g_fg.depth.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    barrier(g_fg.mv.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    barrier(g_fg.back.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    NVSDK_NGX_DLSSG_Create_Params cp{};
    cp.Width = w; cp.Height = h; cp.NativeBackbufferFormat = DXGI_FORMAT_R8G8B8A8_UNORM;
    cp.RenderWidth = w; cp.RenderHeight = h; cp.DynamicResolutionScaling = false;
    g_params->Set(NVSDK_NGX_DLSSG_Parameter_LiteCandidateBlendingEnabled, (unsigned)(lite ? 1 : 0));
    NVSDK_NGX_Result r = NGX_D3D12_CREATE_DLSSG(g_list.Get(), 1, 1, &g_fg.handle, g_params, &cp);
    g_list->Close();
    ID3D12CommandList* lists[] = {g_list.Get()};
    g_queue->ExecuteCommandLists(1, lists);
    wait_gpu();
    if (NVSDK_NGX_FAILED(r)) return fail("creating DLSS Frame Generation", r);
    *in_h = g_fg.inH; *in_size = g_fg.inSize; *mv_h = g_fg.mvH; *mv_size = g_fg.mvSize;
    *out_h = g_fg.outH; *out_size = g_fg.outSize; *pitch = g_fg.pitch;
    *depth_h = g_fg.depthH; *depth_size = g_fg.depthSize;
    return 1;
}

// Frame `index` (1..count) between the previous real frame and this one. new_real: the shared frame and motion
// buffers hold a new real frame (copied in before the first index). reset: no previous frame to go from.
KVLR_API int kvlr_fg_eval2(int new_real, unsigned count, unsigned index, int reset, int use_depth, int mv_dilated,
                           float* gpu_ms);
KVLR_API int kvlr_fg_eval(int new_real, unsigned count, unsigned index, int reset, float* gpu_ms) {
    return kvlr_fg_eval2(new_real, count, index, reset, 0, 0, gpu_ms);
}
// use_depth: the shared depth buffer holds this frame's estimated depth (1 near, 0 far: DLSS-G's "inverted" depth).
// mv_dilated: tell DLSS-G the motion vectors are already spread over object edges.
KVLR_API int kvlr_fg_eval2(int new_real, unsigned count, unsigned index, int reset, int use_depth, int mv_dilated,
                           float* gpu_ms) {
    std::lock_guard<std::recursive_mutex> lk(g_lock);
    if (!g_fg.handle) return fail("DLSS Frame Generation not created");
    g_alloc->Reset(); g_list->Reset(g_alloc.Get(), nullptr);
    if (new_real) {
        for (auto pr : {std::make_pair(g_fg.back.Get(), std::make_pair(g_fg.inBuf.Get(), DXGI_FORMAT_R8G8B8A8_UNORM)),
                        std::make_pair(g_fg.mv.Get(), std::make_pair(g_fg.mvBuf.Get(), DXGI_FORMAT_R16G16_FLOAT))}) {
            barrier(pr.first, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_TEXTURE_COPY_LOCATION dst{pr.first, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
            D3D12_TEXTURE_COPY_LOCATION src{pr.second.first, D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            src.PlacedFootprint.Offset = 0;
            src.PlacedFootprint.Footprint = {pr.second.second, g_fg.w, g_fg.h, 1, g_fg.pitch};
            g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            barrier(pr.first, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        if (use_depth) {
            barrier(g_fg.depth.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_TEXTURE_COPY_LOCATION dst{g_fg.depth.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
            D3D12_TEXTURE_COPY_LOCATION src{g_fg.depthBuf.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            src.PlacedFootprint.Offset = 0;
            src.PlacedFootprint.Footprint = {DXGI_FORMAT_R32_FLOAT, g_fg.w, g_fg.h, 1, g_fg.pitch};
            g_list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            barrier(g_fg.depth.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
    }
    NVSDK_NGX_D3D12_DLSSG_Eval_Params ep{};
    ep.pBackbuffer = g_fg.back.Get();
    ep.pDepth = g_fg.depth.Get();
    ep.pMVecs = g_fg.mv.Get();
    ep.pOutputInterpFrame = g_fg.out.Get();
    NVSDK_NGX_DLSSG_Opt_Eval_Params op{};
    op.multiFrameCount = count; op.multiFrameIndex = index;
    const float I[4][4] = {{1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 1, 0}, {0, 0, 0, 1}};
    memcpy(op.cameraViewToClip, I, sizeof I); memcpy(op.clipToCameraView, I, sizeof I);
    memcpy(op.clipToLensClip, I, sizeof I); memcpy(op.clipToPrevClip, I, sizeof I); memcpy(op.prevClipToClip, I, sizeof I);
    op.mvecScale[0] = 1.0f; op.mvecScale[1] = 1.0f;
    op.cameraUp[1] = 1.0f; op.cameraRight[0] = 1.0f; op.cameraFwd[2] = 1.0f;
    op.cameraNear = 0.1f; op.cameraFar = 1000.0f; op.cameraFOV = 1.0f;
    op.cameraAspectRatio = (float)g_fg.w / g_fg.h;
    op.cameraMotionIncluded = true;
    op.depthInverted = use_depth != 0;  // estimated depth: 1 near, 0 far (the constant default depth is 0 either way)
    op.motionVectorsDilated = mv_dilated != 0;
    op.reset = reset != 0;
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
    NVSDK_NGX_Result r = NGX_D3D12_EVALUATE_DLSSG(g_list.Get(), g_fg.handle, g_params, &ep, &op);
    g_list->EndQuery(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
    g_list->ResolveQueryData(g_queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, g_queryReadback.Get(), 0);
    barrier(g_fg.out.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION odst{g_fg.outBuf.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    odst.PlacedFootprint.Offset = 0;
    odst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, g_fg.w, g_fg.h, 1, g_fg.pitch};
    D3D12_TEXTURE_COPY_LOCATION osrc{g_fg.out.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; osrc.SubresourceIndex = 0;
    g_list->CopyTextureRegion(&odst, 0, 0, 0, &osrc, nullptr);
    barrier(g_fg.out.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    g_list->Close();
    ID3D12CommandList* lists[] = {g_list.Get()};
    g_queue->ExecuteCommandLists(1, lists);
    wait_gpu();
    if (NVSDK_NGX_FAILED(r)) return fail("DLSS Frame Generation evaluate", r);
    if (gpu_ms) {
        UINT64* ts = nullptr; g_queryReadback->Map(0, nullptr, (void**)&ts);
        *gpu_ms = (float)((ts[1] - ts[0]) * 1000.0 / g_tsFreq);
        g_queryReadback->Unmap(0, nullptr);
    }
    return 1;
}

KVLR_API void kvlr_ngx_shutdown() {
    if (g_dev) wait_gpu();
    kvlr_of_destroy();
    release_fg();
    release_shared();
    release_sr();
    if (g_params) { NVSDK_NGX_D3D12_DestroyParameters(g_params); g_params = nullptr; }
    if (g_ngx) { NVSDK_NGX_D3D12_Shutdown1(g_dev.Get()); g_ngx = false; }
    if (g_event) { CloseHandle(g_event); g_event = nullptr; }
    g_queries.Reset(); g_queryReadback.Reset(); g_list.Reset(); g_alloc.Reset(); g_queue.Reset(); g_fence.Reset(); g_dev.Reset();
}
