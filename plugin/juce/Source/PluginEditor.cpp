#include "PluginEditor.h"

CVRiderAudioProcessorEditor::CVRiderAudioProcessorEditor(CVRiderAudioProcessor& p)
    : AudioProcessorEditor(&p), processor(p), generic(p) {
    addAndMakeVisible(generic);
    setResizable(true, true);
    setSize(520, 560);
    startTimerHz(30);
}

void CVRiderAudioProcessorEditor::timerCallback() {
    meters = processor.getMeters();
    repaint(0, 0, getWidth(), kMeterHeight);
}

void CVRiderAudioProcessorEditor::resized() {
    generic.setBounds(getLocalBounds().withTrimmedTop(kMeterHeight));
}

void CVRiderAudioProcessorEditor::paint(juce::Graphics& g) {
    g.fillAll(getLookAndFeel().findColour(juce::ResizableWindow::backgroundColourId));

    auto area = getLocalBounds().removeFromTop(kMeterHeight).reduced(12, 8);
    g.setColour(juce::Colours::white);
    g.setFont(15.0f);
    g.drawText("CV Rider  —  consonant / vowel rider", area.removeFromTop(20), juce::Justification::centredLeft);

    // consonant probability bar: left = vowel, right = consonant
    auto bar = area.removeFromTop(18).reduced(0, 2);
    g.setColour(juce::Colours::darkgrey);
    g.fillRoundedRectangle(bar.toFloat(), 4.0f);
    const float c = juce::jlimit(0.0f, 1.0f, meters.consonantProb);
    g.setColour(juce::Colour::fromRGB(80, 170, 255).interpolatedWith(juce::Colour::fromRGB(255, 150, 60), c));
    g.fillRoundedRectangle(bar.withWidth(juce::roundToInt(bar.getWidth() * c)).toFloat(), 4.0f);
    g.setColour(juce::Colours::white);
    g.setFont(12.0f);
    g.drawText("vowel", bar, juce::Justification::centredLeft);
    g.drawText("consonant", bar, juce::Justification::centredRight);

    g.drawText(juce::String::formatted("level %5.1f dB    vowel gain %+5.1f dB    consonant gain %+5.1f dB    applied %+5.1f dB",
                                       meters.levelDb, meters.vowelGainDb, meters.consGainDb, meters.gainDb),
               area, juce::Justification::centredLeft);
}
