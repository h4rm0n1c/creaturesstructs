// vivarium_client.cpp -- a client for Creatures 1's "Vivarium" DDE service.
//
// Alongside the OLE automation object the kits use (see ../kit-protocol), the
// game publishes a plain Windows DDEML service.  This client opens one
// conversation, optionally pokes or executes a CAOS script, requests one item,
// prints the reply with its exact byte count, and disconnects.
//
//     vivarium_client SysInfo
//     vivarium_client Macro "dde: putv totl 0 0 0"
//     vivarium_client BrainActivity
//     vivarium_client --run "setv var0 2,setv var1 0" BrainActivity
//     vivarium_client --execute "dde: puts [hello]"
//     vivarium_client --topic Science.OLE SysInfo
//
// `Macro <script>` POKEs the script -- a poke only loads it -- and then
// REQUESTs `Macro`, which runs it and replies with its output.
//
// Only a `Macro` request runs anything.  `BrainActivity` just reads the
// conversation's targ, var0 (report mode) and var1 (dendrite type); every run
// starts by resetting targ to the conversation's owner and var0..var9 to 0, and
// a new conversation is reset once on connect.  So a bare `BrainActivity`
// reports the creature selected when the conversation opened, in mode 0, and
// `--run` sets up another mode by EXECUTEing a script first, on the same
// conversation.  (EXECUTE starts the script on the conversation's macro, so
// the values it leaves in targ and var0/var1 are the ones the request reads.)
//
// `--execute` sends XTYP_EXECUTE instead: the script is queued on the world
// scheduler and no data comes back.
//
// One conversation per run on purpose: under Wine, repeated poke/request pairs
// on a single conversation can lose replies or deliver the previous one.
//
// BUILD (32-bit)
//
//     cl /nologo /O2 /EHsc /MT vivarium_client.cpp user32.lib
//     i686-w64-mingw32-g++ -O2 -static vivarium_client.cpp -luser32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ddeml.h>

#include <cstdio>
#include <cstring>
#include <string>

namespace {

HDDEDATA CALLBACK client_callback(UINT, UINT, HCONV, HSZ, HSZ, HDDEDATA,
                                  ULONG_PTR, ULONG_PTR) {
    return nullptr;
}

void print_reply(const unsigned char* bytes, DWORD length) {
    std::printf("%lu bytes: \"", static_cast<unsigned long>(length));
    for (DWORD i = 0; i < length; ++i) {
        unsigned char c = bytes[i];
        if (c == '\0') {
            std::printf("\\0");
        } else if (c < 0x20 || c >= 0x7f) {
            std::printf("\\x%02x", c);
        } else {
            std::putchar(c);
        }
    }
    std::printf("\"\n");
}

// POKE a script at an item and REQUEST it.  Returns the reply handle or null.
HDDEDATA poke_and_request(DWORD instance, HCONV conversation, HSZ item,
                          const std::string& text) {
    DWORD result = 0;
    if (!text.empty() &&
        DdeClientTransaction(reinterpret_cast<LPBYTE>(const_cast<char*>(text.c_str())),
                             static_cast<DWORD>(text.size() + 1), conversation,
                             item, CF_TEXT, XTYP_POKE, 20000, &result) == nullptr) {
        std::fprintf(stderr, "POKE failed (error 0x%04x)\n", DdeGetLastError(instance));
        return nullptr;
    }
    return DdeClientTransaction(nullptr, 0, conversation, item, CF_TEXT,
                                XTYP_REQUEST, 20000, &result);
}

int usage() {
    std::fprintf(stderr,
                 "usage: vivarium_client [--topic T] [--run script] <item> [script]\n"
                 "       vivarium_client [--topic T] --execute <script>\n"
                 "items: Macro BrainActivity BrainWiring SysInfo\n");
    return 2;
}

} // namespace

int main(int argc, char** argv) {
    std::string topic = "Vivarium";
    std::string item_name;
    std::string script;
    std::string setup_script;
    bool execute = false;

    int index = 1;
    if (index + 1 < argc && std::strcmp(argv[index], "--topic") == 0) {
        topic = argv[index + 1];
        index += 2;
    }
    if (index + 1 < argc && std::strcmp(argv[index], "--run") == 0) {
        setup_script = argv[index + 1];
        index += 2;
    }
    if (index < argc && std::strcmp(argv[index], "--execute") == 0) {
        if (index + 1 >= argc) {
            return usage();
        }
        execute = true;
        script = argv[index + 1];
    } else if (index < argc) {
        item_name = argv[index];
        if (index + 1 < argc) {
            script = argv[index + 1];
        }
    } else {
        return usage();
    }

    DWORD instance = 0;
    if (DdeInitializeA(&instance, client_callback,
                       APPCLASS_STANDARD | APPCMD_CLIENTONLY, 0) !=
        DMLERR_NO_ERROR) {
        std::fprintf(stderr, "DdeInitialize failed\n");
        return 1;
    }

    int exit_code = 1;
    HSZ service = DdeCreateStringHandleA(instance, "Vivarium", CP_WINANSI);
    HSZ topic_handle = DdeCreateStringHandleA(instance, topic.c_str(), CP_WINANSI);
    HCONV conversation = DdeConnect(instance, service, topic_handle, nullptr);
    if (conversation == nullptr) {
        std::fprintf(stderr, "DdeConnect failed (error 0x%04x) -- is the game running?\n",
                     DdeGetLastError(instance));
    } else if (execute) {
        DWORD result = 0;
        HDDEDATA sent = DdeClientTransaction(
            reinterpret_cast<LPBYTE>(const_cast<char*>(script.c_str())),
            static_cast<DWORD>(script.size() + 1), conversation, nullptr, CF_TEXT,
            XTYP_EXECUTE, 20000, &result);
        std::printf("EXECUTE %s\n", sent != nullptr ? "acknowledged" : "failed");
        exit_code = sent != nullptr ? 0 : 1;
    } else {
        if (!setup_script.empty()) {
            // EXECUTE, not a Macro POKE+REQUEST: it runs the script the same
            // way, and has no reply for Wine to lose.
            DWORD result = 0;
            HDDEDATA ran = DdeClientTransaction(
                reinterpret_cast<LPBYTE>(const_cast<char*>(setup_script.c_str())),
                static_cast<DWORD>(setup_script.size() + 1), conversation, nullptr,
                CF_TEXT, XTYP_EXECUTE, 20000, &result);
            std::printf("--run: %s\n", ran != nullptr ? "executed" : "EXECUTE failed");
        }
        HSZ item = DdeCreateStringHandleA(instance, item_name.c_str(), CP_WINANSI);
        HDDEDATA reply = poke_and_request(instance, conversation, item, script);
        if (reply == nullptr) {
            // BrainWiring always answers with no data; so does a Macro run
            // that wrote no output.
            std::printf("no data (error 0x%04x)\n", DdeGetLastError(instance));
        } else {
            DWORD length = 0;
            const unsigned char* bytes = DdeAccessData(reply, &length);
            print_reply(bytes, length);
            DdeUnaccessData(reply);
            DdeFreeDataHandle(reply);
            exit_code = 0;
        }
        DdeFreeStringHandle(instance, item);
    }

    if (conversation != nullptr) {
        DdeDisconnect(conversation);
    }
    DdeFreeStringHandle(instance, topic_handle);
    DdeFreeStringHandle(instance, service);
    DdeUninitialize(instance);
    return exit_code;
}
