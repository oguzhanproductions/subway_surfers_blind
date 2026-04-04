from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

import pygame

ISSUE_TITLE_LIMIT: Final[int] = 250
ISSUE_MESSAGE_LIMIT: Final[int] = 1500
WM_KEYDOWN: Final[int] = 0x0100
WM_KEYUP: Final[int] = 0x0101
WM_CHAR: Final[int] = 0x0102
WM_DESTROY: Final[int] = 0x0002
WM_NCDESTROY: Final[int] = 0x0082
WM_SETFONT: Final[int] = 0x0030
EM_SETLIMITTEXT: Final[int] = 0x00C5
EM_SETSEL: Final[int] = 0x00B1
DEFAULT_GUI_FONT: Final[int] = 17
VK_SHIFT: Final[int] = 0x10
VK_ESCAPE: Final[int] = 0x1B
VK_RETURN: Final[int] = 0x0D
VK_BACK: Final[int] = 0x08
WS_CHILD: Final[int] = 0x40000000
WS_VISIBLE: Final[int] = 0x10000000
WS_BORDER: Final[int] = 0x00800000
WS_TABSTOP: Final[int] = 0x00010000
WS_VSCROLL: Final[int] = 0x00200000
WS_EX_CLIENTEDGE: Final[int] = 0x00000200
ES_LEFT: Final[int] = 0x0000
ES_AUTOHSCROLL: Final[int] = 0x0080
ES_MULTILINE: Final[int] = 0x0004
ES_AUTOVSCROLL: Final[int] = 0x0040
ES_WANTRETURN: Final[int] = 0x1000
GWLP_WNDPROC: Final[int] = -4


class NativeIssueDialogError(RuntimeError):
    pass


class IssueDialogCancelled(RuntimeError):
    pass


@dataclass
class _InlineTextInputState:
    parent_hwnd: int
    multiline: bool
    numeric_only: bool = False
    edit_handle: int = 0
    controls: list[int] = field(default_factory=list)
    result: str | None = None
    cancelled: bool = False
    closed: bool = False
    submit_key_blocked: bool = False


_LONG_PTR = ctypes.c_ssize_t
_WINDOWS_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_WNDPROC = _WINDOWS_CALLBACK_FACTORY(_LONG_PTR, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
_USER32 = ctypes.windll.user32
_GDI32 = ctypes.windll.gdi32
_KERNEL32 = ctypes.windll.kernel32
_USER32.SetWindowLongPtrW.restype = _LONG_PTR
_USER32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, _LONG_PTR)
_USER32.CallWindowProcW.restype = _LONG_PTR
_USER32.CallWindowProcW.argtypes = (_LONG_PTR, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
_INLINE_STATES: dict[int, _InlineTextInputState] = {}
_ORIGINAL_EDIT_PROCS: dict[int, int] = {}


def prompt_for_inline_issue_text(
    *,
    caption: str,
    text_hint: str = "",
    multiline: bool,
    text_limit: int,
    numeric_only: bool = False,
) -> str:
    parent_hwnd = int(pygame.display.get_wm_info().get("window", 0) or 0)
    if parent_hwnd <= 0:
        raise NativeIssueDialogError("Windows text input is not available in the current display mode.")
    state = _InlineTextInputState(
        parent_hwnd=parent_hwnd,
        multiline=bool(multiline),
        numeric_only=bool(numeric_only),
    )
    try:
        try:
            _create_inline_controls(
                state,
                caption=str(caption or "").strip() or "Issue Input",
                text_hint=str(text_hint or ""),
                text_limit=int(text_limit),
            )
            _modal_message_loop(state)
        except (ctypes.ArgumentError, OSError) as exc:
            raise NativeIssueDialogError("Windows text input is currently unavailable.") from exc
    finally:
        _destroy_inline_controls(state)
    if state.result is not None:
        return state.result
    if state.cancelled:
        raise IssueDialogCancelled()
    raise NativeIssueDialogError("Windows text input closed unexpectedly.")


def _modal_message_loop(state: _InlineTextInputState) -> None:
    message = wintypes.MSG()
    while not state.closed and _USER32.IsWindow(wintypes.HWND(state.edit_handle)):
        result = _USER32.GetMessageW(ctypes.byref(message), None, 0, 0)
        if result == 0:
            break
        if result == -1:
            raise NativeIssueDialogError("Windows text input message loop failed.")
        _USER32.TranslateMessage(ctypes.byref(message))
        _USER32.DispatchMessageW(ctypes.byref(message))


def _create_inline_controls(
    state: _InlineTextInputState,
    *,
    caption: str,
    text_hint: str,
    text_limit: int,
) -> None:
    parent_handle = wintypes.HWND(state.parent_hwnd)
    client_rect = wintypes.RECT()
    if not _USER32.GetClientRect(parent_handle, ctypes.byref(client_rect)):
        raise NativeIssueDialogError("Unable to size the Windows text input controls.")
    client_width = max(640, int(client_rect.right - client_rect.left))
    client_height = max(480, int(client_rect.bottom - client_rect.top))
    control_width = min(max(540, client_width - 120), 920)
    edit_height = 280 if state.multiline else 36
    total_height = edit_height + 104
    left = max(24, (client_width - control_width) // 2)
    top = max(64, (client_height - total_height) // 2)
    font_handle = _GDI32.GetStockObject(DEFAULT_GUI_FONT)
    caption_handle = _create_static(
        parent_handle,
        caption,
        left,
        top,
        control_width,
        26,
        font_handle,
    )
    hint_text = (
        "Enter submits. Shift+Enter starts a new line. Escape cancels."
        if state.multiline
        else "Enter submits. Escape cancels."
    )
    if state.numeric_only:
        hint_text = "Only numbers are allowed. Enter submits. Escape cancels."
    hint_handle = _create_static(
        parent_handle,
        hint_text,
        left,
        top + 28,
        control_width,
        22,
        font_handle,
    )
    edit_handle = _create_edit(
        parent_handle,
        text_hint,
        left,
        top + 56,
        control_width,
        edit_height,
        font_handle,
        multiline=state.multiline,
        text_limit=text_limit,
    )
    state.edit_handle = edit_handle
    state.controls = [caption_handle, hint_handle, edit_handle]
    state.submit_key_blocked = _return_key_pressed()
    _subclass_inline_edit(edit_handle)
    _INLINE_STATES[int(edit_handle)] = state
    _USER32.SetFocus(wintypes.HWND(edit_handle))
    text_length = len(text_hint)
    _USER32.SendMessageW(wintypes.HWND(edit_handle), EM_SETSEL, text_length, text_length)


def _create_static(
    parent_hwnd: wintypes.HWND,
    text: str,
    x: int,
    y: int,
    width: int,
    height: int,
    font_handle: int,
) -> int:
    handle = _USER32.CreateWindowExW(
        0,
        "STATIC",
        text,
        WS_CHILD | WS_VISIBLE,
        x,
        y,
        width,
        height,
        parent_hwnd,
        None,
        _KERNEL32.GetModuleHandleW(None),
        None,
    )
    if not handle:
        raise NativeIssueDialogError("Unable to create Windows text input label controls.")
    _USER32.SendMessageW(handle, WM_SETFONT, font_handle, True)
    return int(handle)


def _create_edit(
    parent_hwnd: wintypes.HWND,
    text: str,
    x: int,
    y: int,
    width: int,
    height: int,
    font_handle: int,
    *,
    multiline: bool,
    text_limit: int,
) -> int:
    style = WS_CHILD | WS_VISIBLE | WS_BORDER | WS_TABSTOP | ES_LEFT
    if multiline:
        style |= ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN | WS_VSCROLL
    else:
        style |= ES_AUTOHSCROLL
    handle = _USER32.CreateWindowExW(
        WS_EX_CLIENTEDGE,
        "EDIT",
        text,
        style,
        x,
        y,
        width,
        height,
        parent_hwnd,
        None,
        _KERNEL32.GetModuleHandleW(None),
        None,
    )
    if not handle:
        raise NativeIssueDialogError("Unable to create the Windows text input field.")
    _USER32.SendMessageW(handle, WM_SETFONT, font_handle, True)
    _USER32.SendMessageW(handle, EM_SETLIMITTEXT, int(text_limit), 0)
    return int(handle)


def _destroy_inline_controls(state: _InlineTextInputState) -> None:
    for handle in reversed(state.controls):
        if handle and _USER32.IsWindow(wintypes.HWND(handle)):
            _USER32.DestroyWindow(wintypes.HWND(handle))
    state.controls.clear()
    if state.edit_handle:
        _INLINE_STATES.pop(int(state.edit_handle), None)
    _restore_parent_focus(state)


def _subclass_inline_edit(edit_handle: int) -> None:
    previous_window_proc = int(
        _USER32.SetWindowLongPtrW(
            wintypes.HWND(edit_handle),
            GWLP_WNDPROC,
            _window_proc_pointer_value(_INLINE_EDIT_WNDPROC),
        )
    )
    if previous_window_proc:
        _ORIGINAL_EDIT_PROCS[int(edit_handle)] = previous_window_proc


def _window_proc_pointer_value(window_proc: _WNDPROC) -> int:
    return int(ctypes.cast(window_proc, ctypes.c_void_p).value or 0)


def _window_text(handle: int) -> str:
    text_length = _USER32.GetWindowTextLengthW(wintypes.HWND(handle))
    buffer = ctypes.create_unicode_buffer(max(1, text_length + 1))
    _USER32.GetWindowTextW(wintypes.HWND(handle), buffer, len(buffer))
    return str(buffer.value)


def _shift_key_pressed() -> bool:
    return bool(_USER32.GetKeyState(VK_SHIFT) & 0x8000)


def _return_key_pressed() -> bool:
    return bool(_USER32.GetKeyState(VK_RETURN) & 0x8000)


def _is_allowed_numeric_char(char_code: int) -> bool:
    value = int(char_code)
    if value < 32:
        return True
    return 48 <= value <= 57


def _should_submit_inline_text(*, multiline: bool, key: int, shift_pressed: bool) -> bool:
    if int(key) != VK_RETURN:
        return False
    if not multiline:
        return True
    return not bool(shift_pressed)


def _restore_parent_focus(state: _InlineTextInputState) -> None:
    parent_handle = int(state.parent_hwnd or 0)
    if parent_handle <= 0:
        return
    hwnd = wintypes.HWND(parent_handle)
    if _USER32.IsWindow(hwnd):
        for method_name in ("BringWindowToTop", "SetForegroundWindow", "SetActiveWindow", "SetFocus"):
            method = getattr(_USER32, method_name, None)
            if method is None:
                continue
            try:
                method(hwnd)
            except Exception:
                continue


def _finalize_inline_input(state: _InlineTextInputState, *, cancelled: bool) -> None:
    state.cancelled = bool(cancelled)
    if not cancelled:
        state.result = _window_text(state.edit_handle)
    state.closed = True
    if state.edit_handle and _USER32.IsWindow(wintypes.HWND(state.edit_handle)):
        _USER32.DestroyWindow(wintypes.HWND(state.edit_handle))


@_WNDPROC
def _INLINE_EDIT_WNDPROC(hwnd: wintypes.HWND, message: int, wparam: wintypes.WPARAM, lparam: wintypes.LPARAM) -> int:
    state = _INLINE_STATES.get(int(hwnd))
    original_window_proc = _ORIGINAL_EDIT_PROCS.get(int(hwnd))
    if state is not None and int(message) == WM_CHAR and state.numeric_only:
        if not _is_allowed_numeric_char(int(wparam)):
            return 0
    if state is not None and int(message) == WM_KEYDOWN:
        key = int(wparam)
        if key == VK_RETURN and state.submit_key_blocked:
            return 0
        if key == VK_ESCAPE:
            _finalize_inline_input(state, cancelled=True)
            return 0
        if _should_submit_inline_text(
            multiline=state.multiline,
            key=key,
            shift_pressed=_shift_key_pressed(),
        ):
            _finalize_inline_input(state, cancelled=False)
            return 0
    if state is not None and int(message) == WM_KEYUP and int(wparam) == VK_RETURN:
        state.submit_key_blocked = False
    if int(message) in {WM_DESTROY, WM_NCDESTROY}:
        _INLINE_STATES.pop(int(hwnd), None)
        if int(message) == WM_NCDESTROY and original_window_proc is not None:
            _ORIGINAL_EDIT_PROCS.pop(int(hwnd), None)
            _USER32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, original_window_proc)
            return _USER32.CallWindowProcW(original_window_proc, hwnd, message, wparam, lparam)
    if original_window_proc is not None:
        return _USER32.CallWindowProcW(original_window_proc, hwnd, message, wparam, lparam)
    return _LONG_PTR(0)
