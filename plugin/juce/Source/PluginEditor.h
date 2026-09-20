#pragma once

#include "PluginProcessor.h"

// Generic parameter editor plus a small live readout of what the detector is doing.
class CVRiderAudioProcessorEditor final : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit CVRiderAudioProcessorEditor(CVRiderAudioProcessor&);
    ~CVRiderAudioProcessorEditor() override = default;

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;

    CVRiderAudioProcessor& processor;
    juce::GenericAudioProcessorEditor generic;
    cvrider::Meters meters;

    static constexpr int kMeterHeight = 72;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CVRiderAudioProcessorEditor)
};
