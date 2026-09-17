// sfc_ole_client.cpp -- the kit->game half of the C1 kit protocol.
//
// generic_kit.cpp shows what the game sends a kit.  This shows what a kit sends
// back: it connects to the running game's SFC.OLE automation object exactly as
// the shipped kits do, runs one CAOS query, and prints the reply.
//
//     sfc_ole_client "dde: putv totl 0 0 0"
//     sfc_ole_client "dde: getb cnam"
//
// ---------------------------------------------------------------------------
// THE CONVERSATION
//
// SFC.OLE's dispatch map (Creatures.exe, entry array at 0x00458398) gives every
// method lDispID -1, so MFC numbers them by position.  The Macro family:
//
//     1 RequestMacro   2 ExecuteMacro   3 CreateMacro   4 DestroyMacro   5 LoadMacro
//
// all declared "\x4c\x4c": two VTS_PVARIANT, returning VT_BOOL.  The VARIANT's
// type tag is data, not decoration:
//
//     CreateMacro   { VT_I2, execution mode }   -> { VT_I4, holder handle }
//     LoadMacro     { VT_I4, handle }  { VT_BSTR, command buffer }
//     RequestMacro  { VT_I4, handle }  { VT_BSTR, command buffer }  -> reply
//     DestroyMacro  { VT_I4, handle }
//
// CSfcOLE::CreateMacro @ 0x0042fa30 rejects any request tag but VT_I2.  Mode 1
// runs the script to completion and publishes its output; mode 0 would queue it
// on the world scheduler and return nothing.  (CScienceKitSheet::
// ReconnectDdeConversation @ 0x0040bd00 in the original Science Kit builds the
// same {VT_I2, mode} / {VT_I4, handle} pair.)
//
// TWO THINGS THAT LOOK OPTIONAL AND ARE NOT
//
// 1. The command buffer is a byte-length BSTR.  CScienceSheet::ConnectToCreatures
//    @ 0x0040b870 allocates it with OLEAUT32 ordinal 150,
//    SysAllocStringByteLen(NULL, 0x1000), and writes plain ANSI into it.  The
//    length prefix is what the marshaller copies; a plain char[] arrives empty.
//
// 2. RequestMacro replaces your buffer.  CMacroHolder::
//    ExecuteAndPublishMacroOutput @ 0x00419340 frees the BSTR it was given and
//    stores a new one in the VARIANT.  Read the reply from the VARIANT afterwards,
//    never from the pointer you allocated -- and free the new one yourself.
//
// The reply is the script's `dde: putv` / `dde: puts` fields, each ended with
// '|', with the last '|' overwritten by NUL.
//
// ---------------------------------------------------------------------------
// BUILD
//
//     cl /nologo /O2 /EHsc /MT sfc_ole_client.cpp ole32.lib oleaut32.lib
//     i686-w64-mingw32-g++ -O2 -static sfc_ole_client.cpp -lole32 -loleaut32 -luuid
//
// Build 32-bit: SFC.OLE is registered in the 32-bit registry view.  Under Wine
// on a Community Edition install, CreateDispatch reaches the game through
// OLEKitProxy.dll's in-process proxy, which must be registered first
// (regsvr32 OLEKitProxy.dll) -- see README.md.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ole2.h>
#include <oleauto.h>

#include <cstdio>
#include <cstring>

namespace {

enum MacroDispId : DISPID {
    kRequestMacro = 1,
    kExecuteMacro = 2,
    kCreateMacro = 3,
    kDestroyMacro = 4,
    kLoadMacro = 5,
};

const short kExecuteToOutput = 1;

// Invoke a Macro-family method: two VTS_PVARIANT, VT_BOOL result.  Arguments
// travel by reference, as MFC's InvokeHelper passes them, so the server's writes
// into either VARIANT come back to the caller.
bool invoke_macro(IDispatch* sfc, DISPID dispid, VARIANT* first, VARIANT* second) {
    VARIANT args[2];
    VariantInit(&args[0]);
    VariantInit(&args[1]);
    // DISPPARAMS lists arguments last-to-first.
    args[1].vt = VT_VARIANT | VT_BYREF;
    args[1].pvarVal = first;
    args[0].vt = VT_VARIANT | VT_BYREF;
    args[0].pvarVal = second;
    DISPPARAMS params = {args, nullptr, 2, 0};

    VARIANT result;
    VariantInit(&result);
    EXCEPINFO exception{};
    UINT bad_argument = 0;
    const HRESULT hr = sfc->Invoke(dispid, IID_NULL, LOCALE_USER_DEFAULT,
                                   DISPATCH_METHOD, &params, &result,
                                   &exception, &bad_argument);
    if (FAILED(hr)) {
        std::fprintf(stderr, "Invoke(%ld) failed: 0x%08lx\n",
                     static_cast<long>(dispid), static_cast<unsigned long>(hr));
        return false;
    }
    return result.vt == VT_BOOL && result.boolVal != VARIANT_FALSE;
}

} // namespace

int main(int argc, char** argv) {
    const char* script = argc > 1 ? argv[1] : "dde: putv totl 0 0 0";
    if (std::strlen(script) >= 0x1000) {
        std::fprintf(stderr, "script longer than the 0x1000-byte command buffer\n");
        return 2;
    }

    if (FAILED(CoInitialize(nullptr))) {
        return 1;
    }
    int exit_code = 1;
    IDispatch* sfc = nullptr;
    CLSID clsid;
    HRESULT hr = CLSIDFromProgID(L"SFC.OLE", &clsid);
    if (SUCCEEDED(hr)) {
        hr = CoCreateInstance(clsid, nullptr, CLSCTX_SERVER, IID_IDispatch,
                              reinterpret_cast<void**>(&sfc));
    }
    if (FAILED(hr)) {
        // This is the failure a kit reports as "No error message is available."
        std::fprintf(stderr, "cannot reach SFC.OLE: 0x%08lx\n",
                     static_cast<unsigned long>(hr));
        CoUninitialize();
        return 1;
    }

    // CreateMacro: the request tag must be VT_I2.
    VARIANT request, holder;
    VariantInit(&request);
    VariantInit(&holder);
    request.vt = VT_I2;
    request.iVal = kExecuteToOutput;
    holder.vt = VT_I4;
    if (!invoke_macro(sfc, kCreateMacro, &request, &holder)) {
        std::fprintf(stderr, "CreateMacro refused\n");
        sfc->Release();
        CoUninitialize();
        return 1;
    }

    // The command buffer: a byte-length BSTR holding ANSI text.
    BSTR buffer = SysAllocStringByteLen(nullptr, 0x1000);
    if (buffer != nullptr) {
        std::memset(buffer, 0, 0x1000);
        std::memcpy(buffer, script, std::strlen(script));

        VARIANT command;
        VariantInit(&command);
        command.vt = VT_BSTR;
        command.bstrVal = buffer;

        if (invoke_macro(sfc, kLoadMacro, &holder, &command) &&
            invoke_macro(sfc, kRequestMacro, &holder, &command)) {
            // The reply is whatever BSTR the VARIANT holds now.  The game has
            // already freed `buffer` if it published anything.
            const char* reply = reinterpret_cast<const char*>(command.bstrVal);
            UINT length = reply == nullptr ? 0 : SysStringByteLen(command.bstrVal);
            std::printf("%.*s\n", static_cast<int>(length), reply ? reply : "");
            exit_code = 0;
        } else {
            std::fprintf(stderr, "LoadMacro/RequestMacro refused\n");
        }
        SysFreeString(command.bstrVal);
    }

    invoke_macro(sfc, kDestroyMacro, &holder, &holder);
    sfc->Release();
    CoUninitialize();
    return exit_code;
}
