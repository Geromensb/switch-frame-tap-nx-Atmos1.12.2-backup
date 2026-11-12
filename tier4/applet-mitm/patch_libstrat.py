#!/usr/bin/env python3
"""
tier4 libstratosphere patch: non-domain mitm sub-object forwarding.

Upstream libstratosphere only wires a forward service to sub-objects returned
from a mitm command on DOMAIN sessions (sf_hipc_server_domain_session_manager).
On a non-domain session (e.g. a game's vi:u session) SetOutObjectImpl calls
plain RegisterSession -> the sub-session has no forward service -> any command
the wrapper doesn't declare hits ForwardRequest() on a null service -> abort.

This adds a thread-local side channel: a mitm command handler sets
ams::sf::impl::g_tier4_pending_mitm_forward to the forwarded ::Service right
before out.SetValue(); SetOutObjectImpl consumes it and calls RegisterMitmSession
(with forward service) instead. Runs on the same thread / call stack, so the
thread-local is safe.

Idempotent - safe to run every build.
"""
import sys, pathlib

F = pathlib.Path(sys.argv[1]) / "libraries/libstratosphere/include/stratosphere/sf/impl/sf_impl_command_serialization.hpp"
src = F.read_text()

def patch_forwarding(src):
    anchor = '#include <stratosphere/sf/hipc/sf_hipc_server_session_manager.hpp>\n'
    inject = anchor + (
        "\n/* --- tier4 patch: non-domain mitm sub-object forwarding side channel --- */\n"
        "#if AMS_SF_MITM_SUPPORTED\n"
        "#include <memory>\n"
        "namespace ams::sf::impl { inline thread_local ::std::shared_ptr<::Service> g_tier4_pending_mitm_forward{}; }\n"
        "#endif\n"
    )
    assert anchor in src, "anchor include not found"
    src = src.replace(anchor, inject, 1)

    old = "                R_ABORT_UNLESS(manager->RegisterSession(server_handle, std::move(object)));\n"
    new = (
        "#if AMS_SF_MITM_SUPPORTED\n"
        "                if (auto _t4fwd = std::move(::ams::sf::impl::g_tier4_pending_mitm_forward); _t4fwd != nullptr) {\n"
        "                    R_ABORT_UNLESS(manager->RegisterMitmSession(server_handle, std::move(object), std::move(_t4fwd)));\n"
        "                } else\n"
        "#endif\n"
        "                {\n"
        "                    R_ABORT_UNLESS(manager->RegisterSession(server_handle, std::move(object)));\n"
        "                }\n"
    )
    assert old in src, "RegisterSession line not found"
    src = src.replace(old, new, 1)

    print("patch_libstrat: forwarding side channel applied")
    return src

def patch_session_hook(src):
    """v0.7.1: a hook for the session pair behind every out-object.

    svcCreateSession charges the CALLING process's resource limit. The module
    is in the Applet group (application_type 2, for the memory), whose limit is
    6 sessions for every applet together (pm_spec.cpp); two wrapped
    sub-objects per app left the keyboard applet none, and it aborted with
    2001-0132 (LimitReached). The hook lets the module get the pair through sm
    instead, which is charged to sm. Falls back to svcCreateSession."""
    anchor = "namespace ams::sf::impl { inline thread_local ::std::shared_ptr<::Service> g_tier4_pending_mitm_forward{}; }\n#endif\n"
    assert anchor in src, "forwarding side channel missing"
    src = src.replace(anchor, anchor + "namespace ams::sf::impl { inline ::ams::Result (*g_tier4_create_session)(::ams::os::NativeHandle *, ::ams::os::NativeHandle *) = nullptr; }\n", 1)
    old = "                R_ABORT_UNLESS(sf::hipc::CreateSession(std::addressof(server_handle), std::addressof(client_handle)));\n"
    new = (
        "                if (::ams::sf::impl::g_tier4_create_session == nullptr || R_FAILED(::ams::sf::impl::g_tier4_create_session(std::addressof(server_handle), std::addressof(client_handle)))) {\n"
        "                    R_ABORT_UNLESS(sf::hipc::CreateSession(std::addressof(server_handle), std::addressof(client_handle)));\n"
        "                }\n"
    )
    assert old in src, "CreateSession line not found"
    src = src.replace(old, new, 1)
    print("patch_libstrat: session hook applied")
    return src

orig = src
MARK = "g_tier4_pending_mitm_forward"
if MARK in src:
    print("patch_libstrat: forwarding side channel already applied")
else:
    src = patch_forwarding(src)

MARK2 = "g_tier4_create_session"
if MARK2 in src:
    print("patch_libstrat: session hook already applied")
else:
    src = patch_session_hook(src)

# v0.7.16: Atmosphere 1.12.0's b05166d50 ("sf: close request copy handles in
# mitm ForwardRequest"), for older trees. Before it, every copy handle in a
# request the module forwards (am, vi) stayed open in the module: a launcher
# passing its transfer memory to the next game (Kingdom Hearts' collection)
# left its 3 GB pinned after it quit, and pm waited for that memory forever -
# the console hung on a black screen. Built against 1.12.0 (v0.7.13's
# release) it never happened; against 1.11.2 it did.
F3 = pathlib.Path(sys.argv[1]) / "libraries/libstratosphere/source/sf/hipc/sf_hipc_server_session_manager.cpp"
src3 = F3.read_text()
MARK3 = "saved_request.meta.num_copy_handles"
if MARK3 in src3:
    print("patch_libstrat: mitm request copy handles already closed (Atmosphere 1.12.0+)")
else:
    old3 = "        R_TRY(svc::SendSyncRequest(util::GetReference(m_forward_service)->session));\n"
    assert src3.count(old3) == 1, "ForwardRequest's SendSyncRequest not found"
    new3 = (
        "        {\n"
        "            ON_SCOPE_EXIT {\n"
        "                const auto saved_request = hipcParseRequest(const_cast<void *>(m_saved_message.GetPointer()));\n"
        "                for (u32 i = 0; i < saved_request.meta.num_copy_handles; i++) {\n"
        "                    os::CloseNativeHandle(saved_request.data.copy_handles[i]);\n"
        "                }\n"
        "            };\n"
        "\n"
        "            R_TRY(svc::SendSyncRequest(util::GetReference(m_forward_service)->session));\n"
        "        }\n"
    )
    F3.write_text(src3.replace(old3, new3, 1))
    print("patch_libstrat: mitm request copy handles closed after forwarding (backport of Atmosphere b05166d50)")

# NX Paradox: libstratosphere's version gate (hos_version_api.cpp,
# AMS_ABORT_UNLESS(is_safely_tryable_version)) runs in __appInit, before main()
# and before the log opens. A firmware whose major.minor is newer than the
# Atmosphere this is built against aborted the module: 23.5.0 with the 1.12.0
# builds (0.7.21.1, 0.7.22) was a fatal, std::abort in 0100000000000C20, ~20 s
# after every boot (#83). A flag instead: Main logs it and exits, unless
# allow_untested_firmware = 1 (applet_mitm_main.cpp). A .cpp, so a rewrite
# rebuilds only that file.
F4 = pathlib.Path(sys.argv[1]) / "libraries/libstratosphere/source/hos/hos_version_api.cpp"
src4 = F4.read_text()
MARK4 = "g_tier4_untested_firmware"
if MARK4 in src4:
    print("patch_libstrat: firmware version gate already a flag")
else:
    decl4 = "    bool IsUnitTestProgramForSetVersion();\n"
    gate4 = "                AMS_ABORT_UNLESS(is_safely_tryable_version);\n"
    assert src4.count(decl4) == 1, "hos_version_api: IsUnitTestProgramForSetVersion declaration not found"
    assert src4.count(gate4) == 1, "hos_version_api: version gate AMS_ABORT_UNLESS not found"
    src4 = src4.replace(decl4, decl4 + (
        "\n"
        "    /* tier4 patch: a firmware newer than this build's Atmosphere is a flag, not a fatal at boot */\n"
        "    constinit bool g_tier4_untested_firmware = false;\n"
        "    bool Tier4IsUntestedFirmware() { return g_tier4_untested_firmware; }\n"
    ), 1)
    src4 = src4.replace(gate4, "                g_tier4_untested_firmware = !is_safely_tryable_version;\n", 1)
    F4.write_text(src4)
    print("patch_libstrat: firmware version gate is a flag (ams::hos::Tier4IsUntestedFirmware), not an abort")

# only when something changed: rewriting the header bumps its timestamp, and
# make then rebuilds the whole of libstratosphere (30+ minutes)
if src != orig:
    F.write_text(src)
sys.exit(0)


