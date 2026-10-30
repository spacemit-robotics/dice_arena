# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Thin C ABI binding, no duplicate Python business transition table."""

import ctypes


class CupPolicy:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.library.cup_task_create.restype = ctypes.c_void_p
        self.library.cup_task_destroy.argtypes = [ctypes.c_void_p]
        self.library.cup_task_step.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.library.cup_task_confirm_grip.argtypes = [ctypes.c_void_p]
        for name in ("cup_task_state", "cup_task_error"):
            getattr(self.library, name).argtypes = [ctypes.c_void_p]
            getattr(self.library, name).restype = ctypes.c_char_p
        self.pointer = self.library.cup_task_create()
        if not self.pointer:
            raise MemoryError("C++ cup policy allocation failed")

    @property
    def state(self):
        return self.library.cup_task_state(self.pointer).decode()

    def step(self, phase, action):
        if self.library.cup_task_step(self.pointer, phase.encode(), action) != 0:
            raise RuntimeError(self.library.cup_task_error(self.pointer).decode())

    def confirm_grip(self):
        if self.library.cup_task_confirm_grip(self.pointer) != 0:
            raise RuntimeError(self.library.cup_task_error(self.pointer).decode())

    def close(self):
        if self.pointer:
            self.library.cup_task_destroy(self.pointer)
            self.pointer = None
