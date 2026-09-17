// generic_kit.cpp -- a headless stand-in for a Creatures 1 embedded kit.
//
// The game launches this from its ordinary Tools menu like any real kit, but it
// has no MFC, no UI and no dialogs to drive.  It accepts every method name it is
// asked for, logs it, and logs every Invoke with the arguments decoded, so the
// live protocol reports itself.  That is how the game->kit method name was
// recovered: it is a literal nowhere in the game, because the game only ever
// asks for it by name through IDispatch::GetIDsOfNames.
//
// The name is "Communicate".
//
// ---------------------------------------------------------------------------
// WHAT A KIT IS
//
// A kit is a minimal OLE local server: CoInitialize, an IClassFactory registered
// for its CLSID, an IDispatch, a message loop.  That is all this file is.
//
// Its dispatch map declares exactly one method, and every kit declares the same
// one.  From Science Kit.exe's map entry at 0x00412df8:
//
//     name    0x0041649c -> "Communicate"
//     dispid  0xffffffff (auto -> 1)
//     pfn     0x00409b10  CScienceSheet::DispatchInvoke
//     vt      0x0b        VT_BOOL
//     params  0x00416498 -> "\x4c\x4c"   two VTS_PVARIANT
//
// So every message is one call: DISPID 1, DISPATCH_METHOD, VT_BOOL return, two
// VARIANT* arguments, each VT_I4.  The first is a packed header, the second a
// payload:
//
//     header = aux:16 | code:8 | kind:8
//
// CScienceSheet::InvokeAutomationMethod @ 0x0040bfb0 reads only the low byte --
// the kind -- to pick a handler: kind 1 goes to the sheet vtable slot at +0xc8,
// kind 2 to +0xcc, anything else returns TRUE without doing work.
//
// All nine senders in Creatures.exe build this identically:
//
//   sender                                        slot     header              payload
//   ExecuteEmbeddedKitTool @ 004444e0 (native)    launched tool<<16 | 0x0301   0
//   SendYourIdIsMessage... @ 0042d860 (Wine)      launched tool<<16 | 0x0301   0
//   BroadcastEmbeddedControlState @ 004449e0      all      state<<8  | 0x02    0
//   NotifyEmbeddedKit9OfCreatureDeath @ 0040e2d0  9        0x0401              genome filename id
//   FlushFuneralKitDocumentStateWords @ 00435c10  9        0x0401              queued state word
//   NotifyDDEScoreChanged @ 0042f740              8        0x0401              &"Dummy"
//   SFCDoc::UpdateWorld @ 004324e0                8        0x0401              &"Dummy"
//   Creature::Deserialize @ 0040dda0              8        0x0401              &"Dummy"
//   Creature::RemoveFromWorld @ 0040e0d0          8        0x0401              &"Dummy"
//
// Two kinds and two codes:
//   kind 1 code 3  YOUR_ID_IS.  Slot number rides in the header aux field, not
//                  the payload, which is zero.  Sent once, right after launch.
//   kind 1 code 4  here is one integer; its meaning is the receiving kit's
//                  business.
//   kind 2         control state, broadcast to every connected slot, payload 0.
//
// 0x00458170 is the literal string "Dummy".  The four Score Kit senders pass its
// *address* as a VT_I4, which is meaningless as an integer -- the Score Kit reads
// the score itself and ignores the payload.
//
// Beware the decompiler here.  Ghidra renders this call with the `self` argument
// swallowed and the rest shifted left, so the real
//     InvokeHelper(self, 1, 1, 0xb, pvRet, "LL", &v0, &v1)
// prints as
//     InvokeHelper(3, 1, VT_I4, pvRet, "\x0b")
// -- wrong DISPID, wrong return type, and the vtRet push mistaken for the
// parameter-info string.  Read the pushes, not the argument list.
//
// ---------------------------------------------------------------------------
// THE OTHER DIRECTION
//
// Kits drive the game with CAOS over the game's own automation object, SFC.OLE:
// CreateMacro, LoadMacro, RequestMacro, DestroyMacro.  Queries go bare
// (`dde: getb cnam`); scripts that change the world are wrapped
// `inst,<body>,endm`.  sfc_ole_client.cpp in this folder is that direction as a
// runnable client, and the README has the dispatch map and the verb set.
//
// ---------------------------------------------------------------------------
// LAUNCHING
//
// Recovered by having this program report its own argv.  Named switches, not
// positional arguments -- reading argv[1] positionally makes a kit serve slot 0
// while the game talks to slot 6, which is silent and looks like a dead pipe:
//
//     generic_kit.exe /Embedding /ToolID=6 /ProgID=Generic.OLE
//
// Registration:
//     HKCR\<ProgID>\CLSID               -> {CLSID}
//     HKCR\CLSID\{CLSID}\LocalServer32  -> path to this exe
//     HKCU\Software\Gameware Development\Creatures 1\1.0\Tool<N>
//                                        -> "<ProgID>|name|help|<N>"
//
// Build (MSVC):
//     cl /nologo /O2 /EHsc /MT generic_kit.cpp user32.lib ole32.lib oleaut32.lib
//
// Logs to C:\generic_kit.txt.
//
// ---------------------------------------------------------------------------
// A NOTE ON WINE
//
// Under Wine the game does not activate a kit through COM.  It loads
// OLEKitProxy.dll from beside the executable and calls
//     LaunchKitWithInjection(exePath, toolID, progID)
// which launches the kit *and injects itself into it*.  The injected copy runs
// the pipe server for \\.\pipe\Creatures1_Kit_Tool<N> -- so a kit must NOT
// create that pipe itself, which is what ERROR_PIPE_BUSY on startup means --
// hooks CoRegisterClassObject to discover the kit, resolves the ProgID through
// CoGetClassObject/CreateInstance for its IDispatch, and per pipe message calls
// GetIDsOfNames then Invoke.  It offers the kit the reverse direction over
// \\.\pipe\SFC_OLE as CreateMacro / ExecuteMacro / DestroyMacro.
//
// This Wine path is specific to the modern Creatures Exodus/CE build analysed
// here; the 1996 retail binary has only the native COM branch.  The Communicate
// protocol above is the same on both.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <oleauto.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

// Must match the CLSID registered for this kit's ProgID.
// {A1B2C3D4-0001-0002-0003-000400050006}
static const CLSID kGenericKitClsid = {
    0xa1b2c3d4, 0x0001, 0x0002,
    {0x00, 0x03, 0x00, 0x04, 0x00, 0x05, 0x00, 0x06}};

static const char* g_log_path = "C:\\generic_kit.txt";

static void log_line(const char* format, ...) {
    FILE* file = fopen(g_log_path, "a");
    va_list args;
    if (file != NULL) {
        va_start(args, format);
        vfprintf(file, format, args);
        va_end(args);
        fclose(file);
    }
    va_start(args, format);
    vprintf(format, args);
    va_end(args);
    fflush(stdout);
}

static void log_variant(const char* label, const VARIANT* value) {
    if (value == NULL) {
        log_line("    %s: (null)\n", label);
        return;
    }
    VARIANT resolved = *value;
    if ((resolved.vt & VT_BYREF) && (resolved.vt & VT_VARIANT) &&
        resolved.pvarVal != NULL) {
        resolved = *resolved.pvarVal;
    }
    switch (resolved.vt) {
    case VT_I2:
        log_line("    %s: VT_I2 %d\n", label, (int)resolved.iVal);
        break;
    case VT_I4:
        log_line("    %s: VT_I4 %ld\n", label, (long)resolved.lVal);
        break;
    case VT_BOOL:
        log_line("    %s: VT_BOOL %d\n", label, (int)resolved.boolVal);
        break;
    case VT_BSTR: {
        // Kit macro strings are byte-length BSTRs, not always wide text.
        const unsigned int bytes =
            resolved.bstrVal == NULL ? 0u : SysStringByteLen(resolved.bstrVal);
        log_line("    %s: VT_BSTR %u bytes \"%.120s\"\n", label, bytes,
                 resolved.bstrVal == NULL ? "" : (const char*)resolved.bstrVal);
        break;
    }
    default:
        log_line("    %s: vt=0x%04x\n", label, (unsigned)resolved.vt);
        break;
    }
}

class KitDispatch : public IDispatch {
public:
    KitDispatch() : reference_count_(1), known_name_count_(0) {}

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) {
        if (out == NULL) {
            return E_POINTER;
        }
        *out = NULL;
        if (InlineIsEqualGUID(iid, IID_IUnknown) ||
            InlineIsEqualGUID(iid, IID_IDispatch)) {
            *out = static_cast<IDispatch*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() {
        return (ULONG)InterlockedIncrement(&reference_count_);
    }
    ULONG STDMETHODCALLTYPE Release() {
        const LONG remaining = InterlockedDecrement(&reference_count_);
        if (remaining == 0) {
            delete this;
        }
        return (ULONG)remaining;
    }

    HRESULT STDMETHODCALLTYPE GetTypeInfoCount(UINT* count) {
        if (count != NULL) {
            *count = 0;
        }
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetTypeInfo(UINT, LCID, ITypeInfo**) {
        return E_NOTIMPL;
    }

    // Every name the proxy asks for is recorded, then accepted: refusing one
    // would hide the very thing this program exists to discover.
    HRESULT STDMETHODCALLTYPE GetIDsOfNames(REFIID, LPOLESTR* names,
                                            UINT name_count, LCID,
                                            DISPID* ids) {
        for (UINT index = 0; index < name_count; ++index) {
            char narrow[128];
            memset(narrow, 0, sizeof(narrow));
            WideCharToMultiByte(CP_ACP, 0, names[index], -1, narrow,
                                sizeof(narrow) - 1, NULL, NULL);
            if (index == 0) {
                ++known_name_count_;
                ids[index] = (DISPID)known_name_count_;
                log_line("GetIDsOfNames: \"%s\" -> dispid %ld\n", narrow,
                         (long)ids[index]);
            } else {
                ids[index] = DISPID_UNKNOWN;
                log_line("GetIDsOfNames: named arg \"%s\" (unsupported)\n",
                         narrow);
            }
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE Invoke(DISPID id, REFIID, LCID, WORD flags,
                                     DISPPARAMS* params, VARIANT* result,
                                     EXCEPINFO*, UINT*) {
        const UINT count = params == NULL ? 0u : params->cArgs;
        log_line("Invoke: dispid=%ld flags=0x%04x args=%u\n", (long)id,
                 (unsigned)flags, (unsigned)count);
        // DISPPARAMS stores arguments in reverse, so report source order.
        for (UINT index = 0; index < count; ++index) {
            char label[32];
            wsprintfA(label, "arg%u", (unsigned)(count - 1 - index));
            log_variant(label, &params->rgvarg[index]);
        }
        if (result != NULL) {
            VariantInit(result);
            result->vt = VT_BOOL;
            result->boolVal = VARIANT_TRUE;
        }
        return S_OK;
    }

private:
    LONG reference_count_;
    long known_name_count_;
};

class KitClassFactory : public IClassFactory {
public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) {
        if (out == NULL) {
            return E_POINTER;
        }
        *out = NULL;
        if (InlineIsEqualGUID(iid, IID_IUnknown) ||
            InlineIsEqualGUID(iid, IID_IClassFactory)) {
            *out = static_cast<IClassFactory*>(this);
            return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() { return 2; }
    ULONG STDMETHODCALLTYPE Release() { return 1; }

    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID iid,
                                             void** out) {
        log_line("CreateInstance: the proxy is acquiring the kit dispatch\n");
        if (out == NULL) {
            return E_POINTER;
        }
        *out = NULL;
        if (outer != NULL) {
            return CLASS_E_NOAGGREGATION;
        }
        KitDispatch* dispatch = new KitDispatch();
        const HRESULT result = dispatch->QueryInterface(iid, out);
        dispatch->Release();
        return result;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL) { return S_OK; }
};

int main(int argc, char** argv) {
    int tool_index = 0;
    const char* prog_id = "(none)";
    for (int index = 1; index < argc; ++index) {
        if (strncmp(argv[index], "/ToolID=", 8) == 0) {
            tool_index = atoi(argv[index] + 8);
        } else if (strncmp(argv[index], "/ProgID=", 8) == 0) {
            prog_id = argv[index] + 8;
        }
    }

    log_line("\n=== generic_kit start: tool=%d progid=%s ===\n", tool_index,
             prog_id);
    log_line("argv:");
    for (int index = 0; index < argc; ++index) {
        log_line(" \"%s\"", argv[index]);
    }
    log_line("\n");

    const HRESULT initialised = CoInitialize(NULL);
    if (FAILED(initialised)) {
        log_line("CoInitialize failed: 0x%08lx\n", (unsigned long)initialised);
        return 1;
    }

    // OLEKitProxy hooks this call: registering the class object is how the
    // injected shim discovers the kit and acquires its IDispatch.
    static KitClassFactory factory;
    DWORD registration = 0;
    const HRESULT registered = CoRegisterClassObject(
        kGenericKitClsid, static_cast<IClassFactory*>(&factory),
        CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE, &registration);
    if (FAILED(registered)) {
        log_line("CoRegisterClassObject failed: 0x%08lx\n",
                 (unsigned long)registered);
        CoUninitialize();
        return 1;
    }
    log_line("CoRegisterClassObject ok (cookie=%lu); pumping messages\n",
             (unsigned long)registration);

    MSG message;
    while (GetMessageA(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }

    CoRevokeClassObject(registration);
    CoUninitialize();
    log_line("generic_kit: exiting\n");
    return 0;
}
