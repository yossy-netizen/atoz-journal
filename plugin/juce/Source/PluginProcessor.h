#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <array>
#include "CVRider.h"
#include "Presets.h"

namespace ParamID {
    inline constexpr auto vowelTarget   = "vowelTarget";
    inline constexpr auto vowelRange    = "vowelRange";
    inline constexpr auto vowelAttack   = "vowelAttack";
    inline constexpr auto vowelRelease  = "vowelRelease";
    inline constexpr auto vowelTrim     = "vowelTrim";
    inline constexpr auto consTarget    = "consTarget";
    inline constexpr auto consRange     = "consRange";
    inline constexpr auto consAttack    = "consAttack";
    inline constexpr auto consRelease   = "consRelease";
    inline constexpr auto consTrim      = "consTrim";
    inline constexpr auto sensitivity   = "sensitivity";
    inline constexpr auto splitFreq     = "splitFreq";
    inline constexpr auto idleThreshold = "idleThreshold";
    inline constexpr auto lookahead     = "lookahead";
    inline constexpr auto output        = "output";
    inline constexpr auto monitor       = "monitor";
    inline constexpr auto bypass        = "bypass";
}

class CVRiderAudioProcessor final : public juce::AudioProcessor {
public:
    CVRiderAudioProcessor();
    ~CVRiderAudioProcessor() override = default;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    using juce::AudioProcessor::processBlock;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    // Expose our own bypass as the host bypass so the wrappers don't add a separate one that
    // would not be part of the saved state (and so the DAW's bypass button is de-clicked too).
    juce::AudioProcessorParameter* getBypassParameter() const override { return apvts.getParameter(ParamID::bypass); }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return static_cast<int>(cvrider::presets().size()); }
    int getCurrentProgram() override { return currentProgram.load(); }
    void setCurrentProgram(int index) override;
    const juce::String getProgramName(int index) override;
    void changeProgramName(int, const juce::String&) override {}

    void getStateInformation(juce::MemoryBlock& destData) override;
    void setStateInformation(const void* data, int sizeInBytes) override;

    juce::AudioProcessorValueTreeState& getState() { return apvts; }
    cvrider::Meters getMeters() const {
        return { meterLevel.load(std::memory_order_relaxed), meterProb.load(std::memory_order_relaxed),
                 meterGv.load(std::memory_order_relaxed), meterGc.load(std::memory_order_relaxed),
                 meterGain.load(std::memory_order_relaxed) };
    }

    // Meter history for the editor's scope: the audio thread appends a snapshot roughly every 10 ms,
    // the editor drains new frames with readMeterFrames(). Single producer / single consumer.
    static constexpr int kMeterRingSize = 1024;
    int getMeterWritePos() const { return meterWrite.load(std::memory_order_acquire); }
    template <typename Fn> void readMeterFrames(int& readPos, Fn&& fn) const {
        const int w = meterWrite.load(std::memory_order_acquire);
        if (w - readPos > kMeterRingSize) readPos = w - kMeterRingSize;   // fell behind: skip ahead
        for (; readPos < w; ++readPos) fn(meterRing[static_cast<size_t>(readPos % kMeterRingSize)]);
    }

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createLayout();
    cvrider::Params readParams() const;

    juce::AudioProcessorValueTreeState apvts;
    cvrider::CVRider rider;
    // per-field atomics keep this lock-free (a 20-byte atomic struct would need libatomic)
    std::atomic<float> meterLevel { -120.0f }, meterProb { 0.0f }, meterGv { 0.0f }, meterGc { 0.0f }, meterGain { 0.0f };
    std::array<cvrider::Meters, kMeterRingSize> meterRing {};
    std::atomic<int> meterWrite { 0 };
    int meterAccum = 0, meterInterval = 480;
    int reportedLatency = -1;
    std::atomic<int> currentProgram { 0 };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CVRiderAudioProcessor)
};
