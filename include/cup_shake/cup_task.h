// Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
// SPDX-License-Identifier: Apache-2.0
// Serialized C ABI for the C++ business state machine. No hardware access.
#ifndef CUP_TASK_H
#define CUP_TASK_H
#ifdef __cplusplus
extern "C" {
#endif
void* cup_task_create(void);
void cup_task_destroy(void* task);
// action=0 begins phase; action=1 commits success; action=2 latches failure.
// Phases: home,approach,grip,lift,shake,lower,open,return_home,gesture.
int cup_task_step(void* task, const char* phase, int action);
int cup_task_confirm_grip(void* task);   // Explicit external evidence, only after grip.
const char* cup_task_state(void* task);  // Borrowed string, valid until task mutation/destruction.
const char* cup_task_error(void* task);
#ifdef __cplusplus
}
#endif
#endif  // CUP_TASK_H
