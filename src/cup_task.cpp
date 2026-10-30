// Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
// SPDX-License-Identifier: Apache-2.0
// Business invariants are independent of Nero, cameras, games and transport.
#include "cup_shake/cup_task.h"
#include <map>
#include <new>
#include <string>
namespace {
struct Task {
    std::string state = "needs_home", active, error;
    bool grip_confirmed = false;
};
int Reject(Task& task, const char* error) {
    task.error = error;
    return -1;
}
}  // namespace
extern "C" {
void* cup_task_create() { return new (std::nothrow) Task; }
void cup_task_destroy(void* task) { delete static_cast<Task*>(task); }
int cup_task_step(void* pointer, const char* phase, int action) {
    if (!pointer || !phase) return -1;
    auto& task = *static_cast<Task*>(pointer);
    try {
        if (action == 2) {
            task.state = "fault";
            task.active.clear();
            task.error = "operator inspection required";
            return 0;
        }
        if (task.state == "fault") return Reject(task, "fault latched; no automatic recovery/home");
        const std::string name = phase;
        const std::map<std::string, std::pair<std::string, std::string>> transitions = {
            {"approach", {"ready", "approached"}}, {"grip", {"approached", "closed"}}, {"lift", {"closed", "held"}},
            {"shake", {"held", "shaken"}}, {"lower", {"shaken", "lowered"}}, {"open", {"lowered", "released"}},
            {"return_home", {"released", "ready"}}, {"gesture", {"ready", "ready"}}};
        std::pair<std::string, std::string> transition;
        if (name == "home") {
            if (task.state != "needs_home" && task.state != "ready")
                return Reject(task, "home forbidden while possibly holding cup");
            transition = {task.state, "ready"};
        } else {
            auto found = transitions.find(name);
            if (found == transitions.end()) return Reject(task, "unknown phase");
            transition = found->second;
        }
        if (action == 0) {
            if (!task.active.empty() || task.state != transition.first)
                return Reject(task, "phase order or serialization violation");
            if (name == "lift" && !task.grip_confirmed)
                return Reject(task, "physical grip evidence required before lift");
            task.active = name;
            task.error.clear();
            return 0;
        }
        if (action != 1 || task.active != name) return Reject(task, "unmatched phase completion");
        task.state = transition.second;
        task.active.clear();
        if (name == "home" || name == "open" || name == "return_home") task.grip_confirmed = false;
        task.error.clear();
        return 0;
    } catch (...) {
        task.state = "fault";
        return -1;
    }
}
int cup_task_confirm_grip(void* pointer) {
    if (!pointer) return -1;
    auto& task = *static_cast<Task*>(pointer);
    if (task.state != "closed" || !task.active.empty()) return Reject(task, "grip confirmation outside closed phase");
    task.grip_confirmed = true;
    return 0;
}
const char* cup_task_state(void* task) { return task ? static_cast<Task*>(task)->state.c_str() : "invalid"; }
const char* cup_task_error(void* task) { return task ? static_cast<Task*>(task)->error.c_str() : "invalid task"; }
}
