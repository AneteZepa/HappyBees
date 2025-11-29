# HappyBees Firmware CMakeLists.txt
# Build: mkdir build && cd build && cmake .. -DPICO_BOARD=pico2_w && make -j4

cmake_minimum_required(VERSION 3.13)

# Initialize Pico SDK (must be before project())
include(pico_sdk_import.cmake)

project(happybees_firmware C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the SDK
pico_sdk_init()

# Add Edge Impulse SDK
add_subdirectory(edge-impulse-sdk)

# Add the main executable
add_executable(happybees_firmware
    source/main.cpp
)

# Include directories
target_include_directories(happybees_firmware PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
    ${CMAKE_CURRENT_LIST_DIR}/source
    ${CMAKE_CURRENT_LIST_DIR}/mode_summer
    ${CMAKE_CURRENT_LIST_DIR}/model_winter
)

# Link libraries
target_link_libraries(happybees_firmware
    pico_stdlib
    hardware_adc
    hardware_dma
    hardware_i2c
    hardware_flash
    pico_cyw43_arch_lwip_poll
    ei_sdk
)

# Enable USB serial output
pico_enable_stdio_usb(happybees_firmware 1)
pico_enable_stdio_uart(happybees_firmware 0)

# Create UF2 file for flashing
pico_add_extra_outputs(happybees_firmware)

# Compiler flags
target_compile_options(happybees_firmware PRIVATE
    -Wall
    -Wno-unused-function
    -Wno-unused-variable
    -O2
)

# Define EI features
target_compile_definitions(happybees_firmware PRIVATE
    EI_PORTING_RASPBERRYPI_PICO=1
    EI_CLASSIFIER_TFLITE_ENABLE_CMSIS_NN=0
    EIDSP_QUANTIZE_FILTERBANK=0
)
