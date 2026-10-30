# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.16)
project(dice_arena VERSION 0.2.0 LANGUAGES CXX)
include(GNUInstallDirs)
include(CTest)
foreach(directory IN ITEMS CMAKE_INSTALL_DATADIR CMAKE_INSTALL_BINDIR CMAKE_INSTALL_LIBDIR)
    if(IS_ABSOLUTE "${${directory}}")
        message(FATAL_ERROR "${directory} must be relative for a relocatable installation")
    endif()
endforeach()
set(GAME_DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena/game)

# Grasp, shake and placement execution belongs to this application, not a separate SDK package.
add_library(cup_task SHARED src/cup_task.cpp)
target_compile_features(cup_task PUBLIC cxx_std_17)
target_compile_options(cup_task PRIVATE -Wall -Wextra -Werror)
target_include_directories(cup_task PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
install(TARGETS cup_task LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(DIRECTORY python/cup_shake DESTINATION python PATTERN "__pycache__" EXCLUDE)
set(cup_config_directory "/${CMAKE_INSTALL_DATADIR}/dice_arena/config")
file(RELATIVE_PATH CUP_DEVICE_PATH "${cup_config_directory}" "/${CMAKE_INSTALL_BINDIR}/manipulation-device")
file(RELATIVE_PATH CUP_PLAN_PATH "${cup_config_directory}"
    "/${CMAKE_INSTALL_DATADIR}/manipulation/examples/mock_device.yaml")
file(RELATIVE_PATH CUP_POLICY_PATH "${cup_config_directory}" "/${CMAKE_INSTALL_LIBDIR}/libcup_task.so")
configure_file(config/mock.install.json.in ${CMAKE_CURRENT_BINARY_DIR}/mock.json @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/mock.json DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena/config)
install(DIRECTORY algorithms calibration DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena
    USE_SOURCE_PERMISSIONS PATTERN "__pycache__" EXCLUDE)
install(DIRECTORY tools DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena
    PATTERN "__pycache__" EXCLUDE PATTERN "*.in" EXCLUDE PATTERN "*.cmake.in" EXCLUDE)
install(PROGRAMS calibrate.sh calibrate_web.sh calibration_web_service.sh
    DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena)

# Relative compatibility alias for existing site configurations. Never remove an existing directory.
configure_file(tools/compatibility.cmake.in ${CMAKE_CURRENT_BINARY_DIR}/compatibility.cmake @ONLY)
install(SCRIPT ${CMAKE_CURRENT_BINARY_DIR}/compatibility.cmake)

# The game as the original runs it: backend, web page and local MOSS-TTS with its models.
install(DIRECTORY game/backend game/web game/tts DESTINATION ${GAME_DESTINATION}
    USE_SOURCE_PERMISSIONS PATTERN "__pycache__" EXCLUDE)
install(FILES game/vision/yolov8_objdetect/README.md DESTINATION ${GAME_DESTINATION}/vision/yolov8_objdetect)

# Dice recognition, built where the SpacemiT inference runtime is installed (the K3), against the
# board OpenCV as the original build did.
find_path(DICE_SPACEMIT_ORT_ENV spacemit_ort_env.h)
if(DICE_SPACEMIT_ORT_ENV)
    if(NOT OpenCV_DIR AND EXISTS /opt/opencv-spacemit/lib/cmake/opencv4)
        set(OpenCV_DIR /opt/opencv-spacemit/lib/cmake/opencv4)
    endif()
    enable_language(CXX)
    add_subdirectory(game/vision/yolov8_objdetect)
    get_target_property(DICE_VISION_RPATH yolov8_camera BUILD_RPATH)
    set_target_properties(yolov8_camera PROPERTIES INSTALL_RPATH "${DICE_VISION_RPATH}")
    install(TARGETS yolov8_camera DESTINATION ${GAME_DESTINATION}/vision/yolov8_objdetect/bin)
else()
    message(STATUS "dice recognition not built: SpacemiT ONNX Runtime development files not found")
endif()

# Runtime assets are optional for a source-only Mock installation.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/mediamtx/mediamtx")
    install(PROGRAMS mediamtx/mediamtx DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena/mediamtx)
else()
    message(STATUS "MediaMTX runtime asset is absent; game serving requires runtime resources")
endif()
install(FILES mediamtx/mediamtx.yml mediamtx/LICENSE DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena/mediamtx)
install(FILES THIRD_PARTY.md runtime_assets.json DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena)

install(DIRECTORY python/spacemit_dice_arena DESTINATION python PATTERN "__pycache__" EXCLUDE)
install(FILES tests/check_game.py tests/check_runtime.py tests/check_tts_startup.py
    DESTINATION ${CMAKE_INSTALL_DATADIR}/dice_arena/tests)
file(RELATIVE_PATH COMMAND_PREFIX_FROM_BINDIR "/${CMAKE_INSTALL_BINDIR}" "/")
foreach(COMMAND_NAME IN ITEMS dice-arena cup-shake)
    if(COMMAND_NAME STREQUAL "dice-arena")
        set(COMMAND_MODULE spacemit_dice_arena.operator)
    else()
        set(COMMAND_MODULE cup_shake.operator)
    endif()
    configure_file(tools/command.in ${CMAKE_CURRENT_BINARY_DIR}/${COMMAND_NAME} @ONLY)
    install(PROGRAMS ${CMAKE_CURRENT_BINARY_DIR}/${COMMAND_NAME} DESTINATION ${CMAKE_INSTALL_BINDIR})
endforeach()

if(BUILD_TESTING)
    set(MANIPULATION_DEVICE "" CACHE FILEPATH "Device executable for full Mock integration tests")
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    add_test(NAME dice_arena_resources
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_assets.py)
    add_test(NAME dice_arena_cup_contract
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_cup.py)
    set_tests_properties(dice_arena_cup_contract PROPERTIES TIMEOUT 30)
    set_property(TEST dice_arena_cup_contract PROPERTY ENVIRONMENT
        "CUP_TASK_LIBRARY=$<TARGET_FILE:cup_task>"
        "MANIPULATION_DEVICE=${MANIPULATION_DEVICE}"
        "DICE_COMPATIBILITY_SCRIPT=${CMAKE_CURRENT_BINARY_DIR}/compatibility.cmake"
        "DICE_DATADIR=${CMAKE_INSTALL_DATADIR}"
        "PYTHONDONTWRITEBYTECODE=1")
    add_test(NAME dice_arena_calibration COMMAND ${Python3_EXECUTABLE} -m pytest -q -p no:cacheprovider
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/calibration)
    set_tests_properties(dice_arena_calibration PROPERTIES TIMEOUT 300 ENVIRONMENT
        "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR};PYTHONNOUSERSITE=1;PYTHONDONTWRITEBYTECODE=1;MANIPULATION_PREFIX=${CMAKE_INSTALL_PREFIX}")
    add_test(NAME dice_arena_algorithms COMMAND ${Python3_EXECUTABLE} -m pytest -q -p no:cacheprovider
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/algorithms)
    set_tests_properties(dice_arena_algorithms PROPERTIES TIMEOUT 600 ENVIRONMENT
        "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/algorithms;PYTHONNOUSERSITE=1;PYTHONDONTWRITEBYTECODE=1")
endif()
