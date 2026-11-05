// Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
// SPDX-License-Identifier: Apache-2.0
/**
 * @file cup_task.h
 * @brief C ABI of the cup task state machine: phase order and failure latching.
 *
 * The state machine never accesses hardware. Calls on one task must be serialized.
 * Phases: home, approach, grip, lift, shake, lower, open, return_home, gesture.
 */
#ifndef CUP_SHAKE_CUP_TASK_H_
#define CUP_SHAKE_CUP_TASK_H_
#ifdef __cplusplus
extern "C" {
#endif
/**
 * @brief Create a task in the idle state.
 * @return Task handle, or NULL when memory is exhausted.
 */
void* cup_task_create(void);

/**
 * @brief Destroy a task; NULL is ignored.
 */
void cup_task_destroy(void* task);

/**
 * @brief Begin or finish a phase.
 *
 * @param task Task handle.
 * @param phase Phase name.
 * @param action 0 begins the phase, 1 commits its success, 2 latches a failure.
 * @return 0 when accepted; -1 when rejected (see cup_task_error()). A latched task rejects every
 *         later phase; there is no automatic recovery or homing.
 */
int cup_task_step(void* task, const char* phase, int action);

/**
 * @brief Record external evidence that the cup is held, allowed only after grip.
 * @return 0 when accepted, -1 when rejected.
 */
int cup_task_confirm_grip(void* task);

/**
 * @brief Current state name.
 * @return Borrowed string, valid until the task changes or is destroyed; "invalid" for NULL.
 */
const char* cup_task_state(void* task);

/**
 * @brief Reason for the last rejection.
 * @return Borrowed string, valid until the task changes or is destroyed; "invalid task" for NULL.
 */
const char* cup_task_error(void* task);
#ifdef __cplusplus
}
#endif
#endif  // CUP_SHAKE_CUP_TASK_H_
