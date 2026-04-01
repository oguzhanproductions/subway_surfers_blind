import ctypes
import unittest
from unittest.mock import patch

from subway_blind import native_windows_issue_dialog as issue_dialog


class NativeWindowsIssueDialogTests(unittest.TestCase):
    def test_single_line_enter_submits_without_control(self):
        self.assertTrue(
            issue_dialog._should_submit_inline_text(
                multiline=False,
                key=issue_dialog.VK_RETURN,
                shift_pressed=False,
            )
        )

    def test_multiline_enter_submits_without_shift(self):
        self.assertTrue(
            issue_dialog._should_submit_inline_text(
                multiline=True,
                key=issue_dialog.VK_RETURN,
                shift_pressed=False,
            )
        )

    def test_multiline_shift_enter_keeps_new_line_behavior(self):
        self.assertFalse(
            issue_dialog._should_submit_inline_text(
                multiline=True,
                key=issue_dialog.VK_RETURN,
                shift_pressed=True,
            )
        )

    def test_non_enter_key_never_submits(self):
        self.assertFalse(
            issue_dialog._should_submit_inline_text(
                multiline=False,
                key=issue_dialog.VK_ESCAPE,
                shift_pressed=False,
            )
        )

    def test_window_proc_pointer_value_returns_integer_pointer(self):
        pointer_value = issue_dialog._window_proc_pointer_value(issue_dialog._INLINE_EDIT_WNDPROC)

        self.assertIsInstance(pointer_value, int)
        self.assertGreater(pointer_value, 0)

    def test_prompt_wraps_native_argument_errors(self):
        with patch("pygame.display.get_wm_info", return_value={"window": 123}), patch(
            "subway_blind.native_windows_issue_dialog._create_inline_controls",
            side_effect=ctypes.ArgumentError(),
        ):
            with self.assertRaises(issue_dialog.NativeIssueDialogError):
                issue_dialog.prompt_for_inline_issue_text(
                    caption="Bug Report Title",
                    multiline=False,
                    text_limit=issue_dialog.ISSUE_TITLE_LIMIT,
                )

    def test_restore_parent_focus_targets_parent_window(self):
        state = issue_dialog._InlineTextInputState(parent_hwnd=9876, multiline=False)

        with patch.object(issue_dialog._USER32, "IsWindow", return_value=True), patch.object(
            issue_dialog._USER32,
            "BringWindowToTop",
        ) as bring_to_top, patch.object(
            issue_dialog._USER32,
            "SetForegroundWindow",
        ) as set_foreground, patch.object(
            issue_dialog._USER32,
            "SetActiveWindow",
        ) as set_active, patch.object(
            issue_dialog._USER32,
            "SetFocus",
        ) as set_focus:
            issue_dialog._restore_parent_focus(state)

        bring_to_top.assert_called_once()
        set_foreground.assert_called_once()
        set_active.assert_called_once()
        set_focus.assert_called_once()


if __name__ == "__main__":
    unittest.main()
