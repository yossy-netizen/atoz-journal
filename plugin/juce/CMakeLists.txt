# Consonant / Vowel Rider — JUCE plugin build
#
#   cmake -B build -DCMAKE_BUILD_TYPE=Release            # fetches JUCE 8 automatically
#   cmake --build build --config Release
#
# Or point at an existing JUCE checkout:
#   cmake -B build -DJUCE_DIR=/path/to/JUCE
cmake_minimum_required(VERSION 3.22)

# macOS: universal binary (Apple Silicon + Intel/Rosetta hosts), macOS 11+.
# Must be set before project().
if(APPLE AND NOT CMAKE_OSX_ARCHITECTURES)
    set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "" FORCE)
endif()
if(APPLE AND NOT CMAKE_OSX_DEPLOYMENT_TARGET)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "" FORCE)
endif()

project(CVRider VERSION 0.2.1 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(JUCE_DIR)
    add_subdirectory(${JUCE_DIR} ${CMAKE_BINARY_DIR}/JUCE)
else()
    include(FetchContent)
    FetchContent_Declare(JUCE
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG        8.0.4
        GIT_SHALLOW    TRUE)
    FetchContent_MakeAvailable(JUCE)
endif()

option(CVRIDER_COPY_AFTER_BUILD "Install the plugin into the user plug-in folders after building" OFF)

set(CVRIDER_FORMATS VST3 Standalone)
if(APPLE)
    list(APPEND CVRIDER_FORMATS AU)
endif()

juce_add_plugin(CVRider
    COMPANY_NAME                "AtoZ Studio"
    PLUGIN_MANUFACTURER_CODE    AtoZ
    PLUGIN_CODE                 Cvrd
    FORMATS                     ${CVRIDER_FORMATS}
    PRODUCT_NAME                "CV Rider"
    IS_SYNTH                    FALSE
    NEEDS_MIDI_INPUT            FALSE
    NEEDS_MIDI_OUTPUT           FALSE
    COPY_PLUGIN_AFTER_BUILD     ${CVRIDER_COPY_AFTER_BUILD}
    BUNDLE_ID                   com.atoz-studio.cvrider
    VST3_CATEGORIES             Fx Dynamics
    AU_MAIN_TYPE                kAudioUnitType_Effect)

target_sources(CVRider PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp)

target_include_directories(CVRider PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../cpp)

target_compile_definitions(CVRider PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(CVRider PRIVATE
    juce::juce_audio_utils
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags)
