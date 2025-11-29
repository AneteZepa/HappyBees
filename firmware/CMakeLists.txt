cmake_minimum_required(VERSION 3.13)

# =============================================================================
# BOARD CONFIGURATION
# =============================================================================
set(PICO_BOARD pico2_w)

# SDK Location
if (NOT DEFINED ENV{PICO_SDK_PATH})
    set(PICO_SDK_PATH ${CMAKE_CURRENT_LIST_DIR}/../pico-sdk)
    set(ENV{PICO_SDK_PATH} ${PICO_SDK_PATH})
endif()

include(pico_sdk_import.cmake)

# =============================================================================
# PROJECT DEFINITION
# =============================================================================
project(beewatch_firmware C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

# =============================================================================
# MODEL SELECTION
# =============================================================================
set(MODEL_DIR "mode_summer")

# =============================================================================
# INCLUDE PATHS
# =============================================================================
include_directories(
    .
    source/
    edge-impulse-sdk/
    edge-impulse-sdk/classifier/
    edge-impulse-sdk/dsp/
    edge-impulse-sdk/porting/
    edge-impulse-sdk/tensorflow/
    edge-impulse-sdk/third_party/
    edge-impulse-sdk/third_party/flatbuffers/include
    edge-impulse-sdk/third_party/gemmlowp
    edge-impulse-sdk/third_party/ruy
    edge-impulse-sdk/CMSIS/DSP/Include/
    edge-impulse-sdk/CMSIS/Core/Include/
    edge-impulse-sdk/CMSIS/NN/Include/
    ${MODEL_DIR}/
    ${MODEL_DIR}/tflite-model/
    ${MODEL_DIR}/model-parameters/
)

# =============================================================================
# SOURCE FILES
# =============================================================================
# Edge Impulse SDK sources
file(GLOB_RECURSE EI_SDK_SOURCES
    "edge-impulse-sdk/classifier/*.cpp"
    "edge-impulse-sdk/dsp/*.cpp"
    "edge-impulse-sdk/porting/*.cpp"
    "edge-impulse-sdk/tensorflow/*.c"
    "edge-impulse-sdk/tensorflow/*.cpp"
    "edge-impulse-sdk/tensorflow/*.cc"
)

# Model-specific sources
file(GLOB MODEL_SOURCES "${MODEL_DIR}/tflite-model/*.cpp")

# =============================================================================
# EXECUTABLE
# =============================================================================
add_executable(beewatch_firmware
    source/main.cpp
    ${EI_SDK_SOURCES}
    ${MODEL_SOURCES}
)

# =============================================================================
# COMPILER DEFINITIONS
# =============================================================================
target_compile_definitions(beewatch_firmware PRIVATE
    # Edge Impulse platform
    EI_PORTING_PICO=1
    
    # TFLite configuration
    TF_LITE_STATIC_MEMORY
    EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN=0
    
    # Disable external CMSIS usage - use EI's internal DSP
    EIDSP_USE_CMSIS_DSP=0
    EI_CLASSIFIER_TFLITE_ENABLE_CMSIS_NN=0
    
    # ARM architecture flags
    __FPU_PRESENT=1
    ARM_MATH_CM33
    __DSP_PRESENT=1
    
    # Release mode
    NDEBUG
    
    # Required for CMSIS headers
    __STATIC_FORCEINLINE=__attribute__\(\(always_inline\)\)\ static\ inline
)

# =============================================================================
# LINK LIBRARIES (UPDATED FOR WIFI/HTTP)
# =============================================================================
target_link_libraries(beewatch_firmware
    pico_stdlib
    hardware_adc
    hardware_dma
    hardware_i2c
    hardware_irq
    hardware_flash          # NEW: For Config Persistence
    hardware_sync           # NEW: For Critical Section during Flash write
    pico_cyw43_arch_lwip_poll # NEW: Replaces arch_none. Enables TCP/IP stack.
)

# =============================================================================
# OUTPUT CONFIGURATION
# =============================================================================
pico_enable_stdio_usb(beewatch_firmware 1)
pico_enable_stdio_uart(beewatch_firmware 0)
pico_add_extra_outputs(beewatch_firmware)

# =============================================================================
# BUILD INFO
# =============================================================================
message(STATUS "BeeWatch Firmware Configuration:")
message(STATUS "  Board: ${PICO_BOARD}")
message(STATUS "  Networking: LWIP Poll Mode")
