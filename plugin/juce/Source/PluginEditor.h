#pragma once

#include "PluginProcessor.h"

namespace ui {
    const juce::Colour bg      { 0xff14161a };
    const juce::Colour panel   { 0xff1e2126 };
    const juce::Colour panel2  { 0xff262a31 };
    const juce::Colour line    { 0xff343941 };
    const juce::Colour text    { 0xffe8eaee };
    const juce::Colour muted   { 0xff9aa1ab };
    const juce::Colour vowel   { 0xff55aaff };
    const juce::Colour cons    { 0xffff9a3c };
    const juce::Colour neutral { 0xff8f9bb0 };
}

// Dark look for the whole editor; rotary knobs drawn as an arc in the group's accent colour.
class CVRiderLookAndFeel final : public juce::LookAndFeel_V4 {
public:
    CVRiderLookAndFeel();
    void drawRotarySlider(juce::Graphics&, int x, int y, int w, int h, float pos,
                          float startAngle, float endAngle, juce::Slider&) override;
    juce::Label* createSliderTextBox(juce::Slider&) override;
};

// A titled panel holding a row of rotary knobs bound to APVTS parameters.
class ParamGroup final : public juce::Component {
public:
    ParamGroup(juce::AudioProcessorValueTreeState&, juce::String title, juce::Colour accent,
               std::initializer_list<std::pair<const char*, const char*>> params);   // {id, label}
    void paint(juce::Graphics&) override;
    void resized() override;

private:
    struct Knob {
        juce::Slider slider;
        juce::Label label;
        std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    };
    juce::String title;
    juce::Colour accent;
    std::vector<std::unique_ptr<Knob>> knobs;
};

// Scrolling history of consonant probability, applied gain and input level.
class Scope final : public juce::Component {
public:
    void push(const cvrider::Meters&);
    void paint(juce::Graphics&) override;

private:
    static constexpr int kLen = 600;
    std::array<float, kLen> prob {}, gain {}, level {};
    int write = 0, count = 0;
};

class CVRiderAudioProcessorEditor final : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit CVRiderAudioProcessorEditor(CVRiderAudioProcessor&);
    ~CVRiderAudioProcessorEditor() override;

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;
    void paintMeterPanel(juce::Graphics&, juce::Rectangle<int>);

    CVRiderAudioProcessor& processor;
    CVRiderLookAndFeel lnf;

    juce::ComboBox presetBox;
    juce::ComboBox monitorBox;
    juce::ToggleButton bypassButton { "Bypass" };
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> monitorAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> bypassAttachment;

    ParamGroup vowelGroup, consGroup, detectorGroup, outputGroup;
    Scope scope;

    cvrider::Meters meters;
    int meterReadPos = 0;
    juce::Rectangle<int> meterArea;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CVRiderAudioProcessorEditor)
};
