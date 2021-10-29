cmake_minimum_required(VERSION 3.14)

# Project properties
set(PROJECT_NAMESPACE gepetto)
set(PROJECT_NAME quadruped-reactive-walking)
set(PROJECT_DESCRIPTION "Reactive walking control architecture for quadrupeds")
set(PROJECT_URL "https://github.com/${PROJECT_NAMESPACE}/${PROJECT_NAME}")

# Project options
option(BUILD_PYTHON_INTERFACE "Build the python binding" ON)
option(INSTALL_PYTHON_INTERFACE_ONLY "Install *ONLY* the python bindings" OFF)
option(SUFFIX_SO_VERSION "Suffix library name with its version" ON)
option(BUILD_PYTHON_INTERFACE "install python bindings" ON)

# Project configuration
if(NOT INSTALL_PYTHON_INTERFACE_ONLY)
  set(PROJECT_USE_CMAKE_EXPORT TRUE)
endif()

# JRL-cmakemodule setup
include(FetchContent)
include(cmake/base.cmake)
include(cmake/boost.cmake)
include(cmake/python.cmake)

# Disable -Werror on Unix.
set(CXX_DISABLE_WERROR True)

# Project definition
COMPUTE_PROJECT_ARGS(PROJECT_ARGS LANGUAGES CXX)
project(${PROJECT_NAME} ${PROJECT_ARGS})
CHECK_MINIMAL_CXX_STANDARD(11 REQUIRED)

# Project dependencies
find_package(eclipse-paho-mqtt-c QUIET)
ADD_PROJECT_DEPENDENCY(odri_control_interface REQUIRED)
ADD_PROJECT_DEPENDENCY(osqp REQUIRED)
ADD_PROJECT_DEPENDENCY(eiquadprog REQUIRED)
ADD_PROJECT_DEPENDENCY(pinocchio REQUIRED)
ADD_PROJECT_DEPENDENCY(yaml-cpp CONFIG REQUIRED)

if(BUILD_PYTHON_INTERFACE)
  FINDPYTHON()
  ADD_PROJECT_DEPENDENCY(eigenpy REQUIRED)
  string(REGEX REPLACE "-" "_" PY_NAME ${PROJECT_NAME})
  set(${PY_NAME}_INSTALL_DIR ${PYTHON_SITELIB}/${PY_NAME})
  SEARCH_FOR_BOOST_PYTHON()
endif()

# Main Library
set(${PROJECT_NAME}_HEADERS
  include/qrw/MPC.hpp
  include/qrw/Gait.hpp
  include/qrw/FootTrajectoryGenerator.hpp
  include/qrw/FootstepPlanner.hpp
  include/qrw/StatePlanner.hpp
  include/qrw/Types.h
  include/qrw/InvKin.hpp
  include/qrw/QPWBC.hpp
  include/qrw/Params.hpp
  include/qrw/Estimator.hpp
  include/qrw/Joystick.hpp
  include/qrw/Filter.hpp
  include/qrw/Controller.hpp
  include/qrw/MpcWrapper.hpp
  include/qrw/FakeRobot.hpp
  include/other/st_to_cc.hpp
  )

set(${PROJECT_NAME}_SOURCES
  src/st_to_cc.cpp
  src/MPC.cpp
  src/Gait.cpp
  src/FootTrajectoryGenerator.cpp
  src/FootstepPlanner.cpp
  src/StatePlanner.cpp
  src/InvKin.cpp
  src/QPWBC.cpp
  src/Params.cpp
  src/Estimator.cpp
  src/Joystick.cpp
  src/Filter.cpp
  src/Controller.cpp
  src/MpcWrapper.cpp
  )

add_library(${PROJECT_NAME} SHARED ${${PROJECT_NAME}_SOURCES} ${${PROJECT_NAME}_HEADERS})
target_include_directories(${PROJECT_NAME} PUBLIC $<INSTALL_INTERFACE:include>)
set_target_properties(${PROJECT_NAME} PROPERTIES INSTALL_RPATH "\$ORIGIN")

target_link_libraries(${PROJECT_NAME} PUBLIC
  eiquadprog::eiquadprog
  pinocchio::pinocchio
  master_board_sdk::master_board_sdk
  odri_control_interface::odri_control_interface
  osqp::osqp
  ${YAML_CPP_LIBRARIES}
  )

if(SUFFIX_SO_VERSION)
  set_target_properties(${PROJECT_NAME} PROPERTIES SOVERSION ${PROJECT_VERSION})
endif()

target_compile_definitions(${PROJECT_NAME} PUBLIC CONFIG_SOLO12_YAML="${PROJECT_SOURCE_DIR}/scripts/config_solo12.yaml")
target_compile_definitions(${PROJECT_NAME} PUBLIC WALK_PARAMETERS_YAML="${PROJECT_SOURCE_DIR}/src/walk_parameters.yaml")

# MQTT Interface
add_library(mqtt-interface SHARED include/qrw/mqtt-interface.hpp src/mqtt-interface.cpp)
target_include_directories(mqtt-interface PUBLIC $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/include>)

if(eclipse-paho-mqtt-c_FOUND)
  message(INFO "MQTT found")
  target_link_libraries(mqtt-interface PRIVATE eclipse-paho-mqtt-c::paho-mqtt3c eclipse-paho-mqtt-c::paho-mqtt3a)
else()
  message(INFO "MQTT not found. It will be fetched and build")
  FetchContent_Declare(eclipse-paho-mqtt-c GIT_REPOSITORY https://github.com/eclipse/paho.mqtt.c)
  FetchContent_MakeAvailable(eclipse-paho-mqtt-c)
  target_link_libraries(mqtt-interface PRIVATE paho-mqtt3c paho-mqtt3a)
endif()

# Main Executable
# add_executable(${PROJECT_NAMESPACE}-${PROJECT_NAME} src/main.cpp)
add_executable(${PROJECT_NAMESPACE}-${PROJECT_NAME} src/control_solo12.cpp)
target_link_libraries(${PROJECT_NAMESPACE}-${PROJECT_NAME} ${PROJECT_NAME} mqtt-interface)

# Python Bindings
if(BUILD_PYTHON_INTERFACE)
  add_subdirectory(python)
endif()

# Installation
if(NOT INSTALL_PYTHON_INTERFACE_ONLY)
  install(TARGETS ${PROJECT_NAME} ${PROJECT_NAMESPACE}-${PROJECT_NAME} mqtt-interface
    EXPORT ${TARGETS_EXPORT_NAME} LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
endif()
install(PROGRAMS scripts/joystick-launcher/joystick-launcher.py RENAME ${PROJECT_NAMESPACE}-joystick-launcher.py DESTINATION bin)
