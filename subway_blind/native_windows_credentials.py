from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

import pygame

CREDUIWIN_GENERIC: Final[int] = 0x1
CREDUIWIN_CHECKBOX: Final[int] = 0x2
ERROR_CANCELLED: Final[int] = 1223
ERROR_INSUFFICIENT_BUFFER: Final[int] = 122


@dataclass(frozen=True)
class CredentialPromptResult:
    username: str
    password: str
    save_requested: bool = False


class NativeCredentialPromptError(RuntimeError):
    pass


class CredentialPromptCancelled(RuntimeError):
    pass


class CREDUI_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hwndParent", wintypes.HWND),
        ("pszMessageText", wintypes.LPWSTR),
        ("pszCaptionText", wintypes.LPWSTR),
        ("hbmBanner", wintypes.HANDLE),
    ]


def prompt_for_credentials(
    caption: str,
    message: str,
    username_hint: str = "",
    allow_save_checkbox: bool = False,
) -> CredentialPromptResult:
    if ctypes.sizeof(ctypes.c_void_p) == 0:
        raise NativeCredentialPromptError("Native Windows credentials are not available.")
    credui = ctypes.windll.credui
    ole32 = ctypes.windll.ole32
    kernel32 = ctypes.windll.kernel32

    prompt_info = CREDUI_INFO()
    prompt_info.cbSize = ctypes.sizeof(CREDUI_INFO)
    prompt_info.hwndParent = wintypes.HWND(int(pygame.display.get_wm_info().get("window", 0) or 0))
    prompt_info.pszCaptionText = ctypes.c_wchar_p(str(caption))
    prompt_info.pszMessageText = ctypes.c_wchar_p(str(message))
    prompt_info.hbmBanner = None

    auth_package = wintypes.ULONG(0)
    out_buffer = wintypes.LPVOID()
    out_buffer_size = wintypes.ULONG(0)
    save_requested = wintypes.BOOL(False)
    flags = CREDUIWIN_GENERIC | (CREDUIWIN_CHECKBOX if allow_save_checkbox else 0)

    username_buffer = ctypes.create_unicode_buffer(str(username_hint), max(1, len(str(username_hint)) + 1))
    password_buffer = ctypes.create_unicode_buffer("", 1)
    packed_size = wintypes.DWORD(0)

    pack_result = credui.CredPackAuthenticationBufferW(
        0,
        ctypes.cast(username_buffer, wintypes.LPWSTR),
        ctypes.cast(password_buffer, wintypes.LPWSTR),
        None,
        ctypes.byref(packed_size),
    )
    last_error = kernel32.GetLastError()
    in_buffer = None
    if not pack_result and last_error == ERROR_INSUFFICIENT_BUFFER and packed_size.value > 0:
        in_buffer = ctypes.create_string_buffer(packed_size.value)
        if not credui.CredPackAuthenticationBufferW(
            0,
            ctypes.cast(username_buffer, wintypes.LPWSTR),
            ctypes.cast(password_buffer, wintypes.LPWSTR),
            in_buffer,
            ctypes.byref(packed_size),
        ):
            in_buffer = None

    try:
        result = credui.CredUIPromptForWindowsCredentialsW(
            ctypes.byref(prompt_info),
            0,
            ctypes.byref(auth_package),
            in_buffer,
            packed_size.value if in_buffer is not None else 0,
            ctypes.byref(out_buffer),
            ctypes.byref(out_buffer_size),
            ctypes.byref(save_requested),
            flags,
        )
        if result == ERROR_CANCELLED:
            raise CredentialPromptCancelled()
        if result != 0:
            raise NativeCredentialPromptError(f"Credential dialog failed with error code {result}.")

        username = _unpack_credential_field(credui, out_buffer, out_buffer_size.value, field="username")
        password = _unpack_credential_field(credui, out_buffer, out_buffer_size.value, field="password")
        return CredentialPromptResult(
            username=username,
            password=password,
            save_requested=bool(save_requested.value),
        )
    finally:
        if out_buffer:
            _secure_zero_buffer(kernel32, out_buffer, out_buffer_size.value)
            ole32.CoTaskMemFree(out_buffer)
        _secure_zero_string_buffer(kernel32, username_buffer)
        _secure_zero_string_buffer(kernel32, password_buffer)
        if in_buffer is not None:
            _secure_zero_buffer(kernel32, in_buffer, len(in_buffer))


def _unpack_credential_field(credui, auth_buffer, auth_buffer_size: int, field: str) -> str:
    kernel32 = ctypes.windll.kernel32
    initial_size = wintypes.DWORD(256)
    username_buffer = ctypes.create_unicode_buffer(initial_size.value)
    domain_buffer = ctypes.create_unicode_buffer(initial_size.value)
    password_buffer = ctypes.create_unicode_buffer(initial_size.value)
    domain_size = wintypes.DWORD(initial_size.value)
    username_size = wintypes.DWORD(initial_size.value)
    password_size = wintypes.DWORD(initial_size.value)
    success = credui.CredUnPackAuthenticationBufferW(
        0,
        auth_buffer,
        auth_buffer_size,
        username_buffer,
        ctypes.byref(username_size),
        domain_buffer,
        ctypes.byref(domain_size),
        password_buffer,
        ctypes.byref(password_size),
    )
    if not success and kernel32.GetLastError() == ERROR_INSUFFICIENT_BUFFER:
        username_buffer = ctypes.create_unicode_buffer(username_size.value)
        domain_buffer = ctypes.create_unicode_buffer(domain_size.value)
        password_buffer = ctypes.create_unicode_buffer(password_size.value)
        success = credui.CredUnPackAuthenticationBufferW(
            0,
            auth_buffer,
            auth_buffer_size,
            username_buffer,
            ctypes.byref(username_size),
            domain_buffer,
            ctypes.byref(domain_size),
            password_buffer,
            ctypes.byref(password_size),
        )
    if not success:
        raise NativeCredentialPromptError("Unable to unpack credentials returned by Windows.")
    try:
        if field == "username":
            if domain_buffer.value:
                return f"{domain_buffer.value}\\{username_buffer.value}".strip("\\")
            return username_buffer.value
        if field == "password":
            return password_buffer.value
        raise NativeCredentialPromptError("Unknown credential field requested.")
    finally:
        _secure_zero_string_buffer(kernel32, username_buffer)
        _secure_zero_string_buffer(kernel32, domain_buffer)
        _secure_zero_string_buffer(kernel32, password_buffer)


def _secure_zero_string_buffer(kernel32, buffer: ctypes.Array) -> None:
    try:
        kernel32.SecureZeroMemory(ctypes.byref(buffer), ctypes.sizeof(buffer))
    except Exception:
        try:
            ctypes.memset(ctypes.byref(buffer), 0, ctypes.sizeof(buffer))
        except Exception:
            pass


def _secure_zero_buffer(kernel32, buffer, size: int) -> None:
    try:
        kernel32.SecureZeroMemory(buffer, int(size))
    except Exception:
        try:
            ctypes.memset(buffer, 0, int(size))
        except Exception:
            pass
