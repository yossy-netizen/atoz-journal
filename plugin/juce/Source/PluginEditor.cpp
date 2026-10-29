#include "PluginEditor.h"

// ============================================================================ look & feel
CVRiderLookAndFeel::CVRiderLookAndFeel() {
    setColour(juce::ResizableWindow::backgroundColourId, ui::bg);
    setColour(juce::Slider::textBoxTextColourId, ui::text);
    setColour(juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
    setColour(juce::Slider::textBoxBackgroundColourId, juce::Colours::transparentBlack);
    setColour(juce::Slider::textBoxHighlightColourId, ui::vowel.withAlpha(0.4f));
    setColour(juce::Label::textColourId, ui::muted);
    setColour(juce::ComboBox::backgroundColourId, ui::panel2);
    setColour(juce::ComboBox::outlineColourId, ui::line);
    setColour(juce::ComboBox::textColourId, ui::text);
    setColour(juce::ComboBox::arrowColourId, ui::muted);
    setColour(juce::PopupMenu::backgroundColourId, ui::panel2);
    setColour(juce::PopupMenu::textColourId, ui::text);
    setColour(juce::PopupMenu::highlightedBackgroundColourId, ui::line);
    setColour(juce::ToggleButton::textColourId, ui::text);
    setColour(juce::ToggleButton::tickColourId, ui::cons);
    setColour(juce::ToggleButton::tickDisabledColourId, ui::muted);
    setColour(juce::TextEditor::backgroundColourId, ui::panel2);
    setColour(juce::TextEditor::textColourId, ui::text);
    setColour(juce::TextEditor::highlightColourId, ui::vowel.withAlpha(0.4f));
    setColour(juce::CaretComponent::caretColourId, ui::text);
}

void CVRiderLookAndFeel::drawRotarySlider(juce::Graphics& g, int x, int y, int w, int h, float pos,
                                          float startAngle, float endAngle, juce::Slider& slider) {
    const auto bounds = juce::Rectangle<float>(static_cast<float>(x), static_cast<float>(y), static_cast<float>(w), static_cast<float>(h)).reduced(4.0f);
    const float radius = juce::jmin(bounds.getWidth(), bounds.getHeight()) * 0.5f;
    const auto centre = bounds.getCentre();
    const float angle = startAngle + pos * (endAngle - startAngle);
    const float thickness = juce::jmax(2.5f, radius * 0.16f);
    const auto accent = slider.findColour(juce::Slider::rotarySliderFillColourId);

    juce::Path track;
    track.addCentredArc(centre.x, centre.y, radius - thickness, radius - thickness, 0.0f, startAngle, endAngle, true);
    g.setColour(ui::line);
    g.strokePath(track, juce::PathStrokeType(thickness, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));

    // bipolar parameters (range crossing zero) fill from the centre, unipolar from the start
    const bool bipolar = slider.getMinimum() < 0.0 && slider.getMaximum() > 0.0;
    const float zeroPos = bipolar ? static_cast<float>((0.0 - slider.getMinimum()) / (slider.getMaximum() - slider.getMinimum())) : 0.0f;
    const float zeroAngle = startAngle + zeroPos * (endAngle - startAngle);
    juce::Path fill;
    fill.addCentredArc(centre.x, centre.y, radius - thickness, radius - thickness, 0.0f,
                       juce::jmin(zeroAngle, angle), juce::jmax(zeroAngle, angle), true);
    g.setColour(accent);
    g.strokePath(fill, juce::PathStrokeType(thickness, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));

    // pointer
    juce::Path pointer;
    pointer.addRoundedRectangle(-thickness * 0.35f, -radius + thickness * 1.6f, thickness * 0.7f, radius * 0.42f, thickness * 0.3f);
    g.setColour(ui::text);
    g.fillPath(pointer, juce::AffineTransform::rotation(angle).translated(centre));
}

juce::Label* CVRiderLookAndFeel::createSliderTextBox(juce::Slider& slider) {
    auto* l = LookAndFeel_V4::createSliderTextBox(slider);
    l->setFont(juce::Font(juce::FontOptions(12.0f)));
    l->setJustificationType(juce::Justification::centred);
    l->setColour(juce::Label::textColourId, ui::text);
    l->setColour(juce::Label::outlineColourId, ui::line);          // subtle box (the slider may have been created before this L&F was set)
    l->setColour(juce::Label::backgroundColourId, ui::panel2);
    return l;
}

// ============================================================================ parameter group
ParamGroup::ParamGroup(juce::AudioProcessorValueTreeState& state, juce::String t, juce::Colour a,
                       std::initializer_list<std::pair<const char*, const char*>> params)
    : title(std::move(t)), accent(a) {
    for (const auto& [id, label] : params) {
        auto k = std::make_unique<Knob>();
        k->slider.setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag);
        k->slider.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 64, 16);
        k->slider.setColour(juce::Slider::rotarySliderFillColourId, accent);
        k->slider.setPopupDisplayEnabled(false, false, nullptr);
        k->label.setText(label, juce::dontSendNotification);
        k->label.setJustificationType(juce::Justification::centred);
        k->label.setFont(juce::Font(juce::FontOptions(12.0f)));
        k->attachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(state, id, k->slider);
        addAndMakeVisible(k->slider);
        addAndMakeVisible(k->label);
        knobs.push_back(std::move(k));
    }
}

void ParamGroup::paint(juce::Graphics& g) {
    const auto r = getLocalBounds().toFloat();
    g.setColour(ui::panel);
    g.fillRoundedRectangle(r, 8.0f);
    g.setColour(ui::line);
    g.drawRoundedRectangle(r.reduced(0.5f), 8.0f, 1.0f);
    g.setColour(accent);
    g.fillEllipse(12.0f, 11.0f, 8.0f, 8.0f);
    g.setColour(ui::muted);
    g.setFont(juce::Font(juce::FontOptions(12.5f)).boldened());
    g.drawText(title.toUpperCase(), 26, 5, getWidth() - 32, 20, juce::Justification::centredLeft);
}

void ParamGroup::resized() {
    auto area = getLocalBounds().reduced(8, 6).withTrimmedTop(22);
    if (knobs.empty()) return;
    const int w = area.getWidth() / static_cast<int>(knobs.size());
    for (auto& k : knobs) {
        auto cell = area.removeFromLeft(w);
        k->label.setBounds(cell.removeFromTop(16));
        k->slider.setBounds(cell);
    }
}

// ============================================================================ scope
void Scope::push(const cvrider::Meters& m) {
    prob[static_cast<size_t>(write)]  = m.consonantProb;
    gain[static_cast<size_t>(write)]  = m.gainDb;
    level[static_cast<size_t>(write)] = m.levelDb;
    write = (write + 1) % kLen;
    count = juce::jmin(count + 1, kLen);
}

void Scope::paint(juce::Graphics& g) {
    const auto r = getLocalBounds().toFloat();
    g.setColour(juce::Colour(0xff0f1114));
    g.fillRoundedRectangle(r, 6.0f);
    g.setColour(ui::line);
    for (float f : { 0.25f, 0.5f, 0.75f }) g.drawHorizontalLine(static_cast<int>(r.getY() + r.getHeight() * f), r.getX(), r.getRight());
    g.drawRoundedRectangle(r.reduced(0.5f), 6.0f, 1.0f);
    if (count < 2) return;

    const float W = r.getWidth(), H = r.getHeight(), dx = W / static_cast<float>(kLen);
    auto plot = [&](const std::array<float, kLen>& data, auto map, juce::Colour colour, bool fill) {
        juce::Path p;
        for (int i = 0; i < count; ++i) {
            const int idx = (write - count + i + kLen) % kLen;
            const float x = r.getRight() - static_cast<float>(count - 1 - i) * dx;
            const float y = r.getY() + map(data[static_cast<size_t>(idx)]) * H;
            if (i == 0) p.startNewSubPath(x, y); else p.lineTo(x, y);
        }
        if (fill) {
            juce::Path f(p);
            f.lineTo(r.getRight(), r.getBottom());
            f.lineTo(r.getRight() - static_cast<float>(count - 1) * dx, r.getBottom());
            f.closeSubPath();
            g.setColour(colour.withAlpha(0.15f));
            g.fillPath(f);
        }
        g.setColour(colour);
        g.strokePath(p, juce::PathStrokeType(1.5f));
    };
    plot(level, [](float v) { return 1.0f - (juce::jlimit(-60.0f, 0.0f, v) + 60.0f) / 60.0f; }, ui::muted.withAlpha(0.6f), false);
    plot(prob,  [](float v) { return 1.0f - juce::jlimit(0.0f, 1.0f, v); }, ui::cons, true);
    plot(gain,  [](float v) { return 0.5f - juce::jlimit(-12.0f, 12.0f, v) / 24.0f; }, ui::vowel, false);

    g.setFont(juce::Font(juce::FontOptions(10.5f)));
    g.setColour(ui::cons);   g.drawText("c",           r.getX() + 8,  r.getY() + 3, 40, 12, juce::Justification::centredLeft);
    g.setColour(ui::vowel);  g.drawText("gain ±12 dB", r.getX() + 22, r.getY() + 3, 80, 12, juce::Justification::centredLeft);
    g.setColour(ui::muted);  g.drawText("level -60..0 dB", r.getX() + 100, r.getY() + 3, 100, 12, juce::Justification::centredLeft);
}

// ============================================================================ editor
CVRiderAudioProcessorEditor::CVRiderAudioProcessorEditor(CVRiderAudioProcessor& p)
    : AudioProcessorEditor(&p), processor(p),
      vowelGroup(p.getState(), "Vowel", ui::vowel,
                 { { ParamID::vowelTarget, "Target" }, { ParamID::vowelRange, "Range" }, { ParamID::vowelAttack, "Attack" },
                   { ParamID::vowelRelease, "Release" }, { ParamID::vowelTrim, "Trim" } }),
      consGroup(p.getState(), "Consonant", ui::cons,
                { { ParamID::consTarget, "Target" }, { ParamID::consRange, "Range" }, { ParamID::consAttack, "Attack" },
                  { ParamID::consRelease, "Release" }, { ParamID::consTrim, "Trim" } }),
      detectorGroup(p.getState(), "Detector", ui::neutral,
                    { { ParamID::sensitivity, "Sensitivity" }, { ParamID::splitFreq, "Split" },
                      { ParamID::idleThreshold, "Idle" }, { ParamID::lookahead, "Lookahead" } }),
      outputGroup(p.getState(), "Output", ui::neutral, { { ParamID::output, "Output" } }) {
    setLookAndFeel(&lnf);

    for (int i = 0; i < p.getNumPrograms(); ++i) presetBox.addItem("Preset: " + p.getProgramName(i), i + 1);
    presetBox.setSelectedId(p.getCurrentProgram() + 1, juce::dontSendNotification);
    presetBox.onChange = [this] {
        const int idx = presetBox.getSelectedId() - 1;
        if (idx >= 0 && idx != processor.getCurrentProgram()) processor.setCurrentProgram(idx);
    };
    addAndMakeVisible(presetBox);

    monitorBox.addItemList({ "Monitor: Off", "Monitor: Consonants", "Monitor: Vowels" }, 1);
    monitorAttachment = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(p.getState(), ParamID::monitor, monitorBox);
    bypassAttachment  = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(p.getState(), ParamID::bypass, bypassButton);
    addAndMakeVisible(monitorBox);
    addAndMakeVisible(bypassButton);
    addAndMakeVisible(vowelGroup);
    addAndMakeVisible(consGroup);
    addAndMakeVisible(detectorGroup);
    addAndMakeVisible(outputGroup);
    addAndMakeVisible(scope);

    meterReadPos = p.getMeterWritePos();
    setResizable(true, true);
    setResizeLimits(640, 440, 1400, 1000);
    setSize(800, 560);
    startTimerHz(30);
}

CVRiderAudioProcessorEditor::~CVRiderAudioProcessorEditor() { setLookAndFeel(nullptr); }

void CVRiderAudioProcessorEditor::timerCallback() {
    if (presetBox.getSelectedId() != processor.getCurrentProgram() + 1)   // host changed the program
        presetBox.setSelectedId(processor.getCurrentProgram() + 1, juce::dontSendNotification);
    meters = processor.getMeters();
    bool any = false;
    processor.readMeterFrames(meterReadPos, [&](const cvrider::Meters& m) { scope.push(m); any = true; });
    if (any) scope.repaint();
    repaint(meterArea);
}

void CVRiderAudioProcessorEditor::resized() {
    auto area = getLocalBounds().reduced(12);

    auto header = area.removeFromTop(34);
    bypassButton.setBounds(header.removeFromRight(90));
    monitorBox.setBounds(header.removeFromRight(180).reduced(0, 4));
    header.removeFromRight(8);
    presetBox.setBounds(header.removeFromRight(170).reduced(0, 4));
    area.removeFromTop(8);

    auto meterPanel = area.removeFromTop(150);
    meterArea = meterPanel;
    scope.setBounds(meterPanel.reduced(10).withTrimmedTop(64));
    area.removeFromTop(10);

    const int gap = 10;
    auto row1 = area.removeFromTop((area.getHeight() - gap) / 2);
    area.removeFromTop(gap);
    auto row2 = area;
    vowelGroup.setBounds(row1.removeFromLeft((row1.getWidth() - gap) / 2));
    consGroup.setBounds(row1.withTrimmedLeft(gap));
    detectorGroup.setBounds(row2.removeFromLeft(juce::roundToInt(row2.getWidth() * 0.72f)));
    outputGroup.setBounds(row2.withTrimmedLeft(gap));
}

void CVRiderAudioProcessorEditor::paint(juce::Graphics& g) {
    g.fillAll(ui::bg);

    // header
    auto header = getLocalBounds().reduced(12).removeFromTop(34);
    g.setColour(ui::text);
    g.setFont(juce::Font(juce::FontOptions(22.0f)).boldened());
    g.drawText("CV Rider", header.removeFromLeft(110), juce::Justification::centredLeft);
    g.setColour(ui::muted);
    g.setFont(juce::Font(juce::FontOptions(12.5f)));
    g.drawText("consonant / vowel rider", header, juce::Justification::centredLeft);

    paintMeterPanel(g, meterArea);
}

void CVRiderAudioProcessorEditor::paintMeterPanel(juce::Graphics& g, juce::Rectangle<int> panel) {
    if (panel.isEmpty()) return;
    g.setColour(ui::panel);
    g.fillRoundedRectangle(panel.toFloat(), 8.0f);
    g.setColour(ui::line);
    g.drawRoundedRectangle(panel.toFloat().reduced(0.5f), 8.0f, 1.0f);

    auto area = panel.reduced(10);

    // consonant probability bar
    auto bar = area.removeFromTop(20);
    g.setColour(juce::Colour(0xff0f1114));
    g.fillRoundedRectangle(bar.toFloat(), 5.0f);
    const float c = juce::jlimit(0.0f, 1.0f, meters.consonantProb);
    if (c > 0.0f) {
        juce::ColourGradient grad(ui::vowel, static_cast<float>(bar.getX()), 0.0f, ui::cons, static_cast<float>(bar.getRight()), 0.0f, false);
        g.setGradientFill(grad);
        g.fillRoundedRectangle(bar.withWidth(juce::jmax(6, juce::roundToInt(bar.getWidth() * c))).toFloat(), 5.0f);
    }
    g.setColour(ui::text.withAlpha(0.85f));
    g.setFont(juce::Font(juce::FontOptions(11.5f)));
    g.drawText("vowel", bar.reduced(8, 0), juce::Justification::centredLeft);
    g.drawText("consonant", bar.reduced(8, 0), juce::Justification::centredRight);
    area.removeFromTop(6);

    // readouts
    auto row = area.removeFromTop(32);
    const int cellW = row.getWidth() / 4;
    auto cell = [&](const juce::String& name, const juce::String& value, juce::Colour colour) {
        auto r = row.removeFromLeft(cellW).reduced(3, 0);
        g.setColour(ui::panel2);
        g.fillRoundedRectangle(r.toFloat(), 5.0f);
        g.setColour(ui::muted);
        g.setFont(juce::Font(juce::FontOptions(10.5f)));
        g.drawText(name, r.reduced(8, 2), juce::Justification::topLeft);
        g.setColour(colour);
        g.setFont(juce::Font(juce::FontOptions(14.0f)).boldened());
        g.drawText(value, r.reduced(8, 1), juce::Justification::bottomLeft);
    };
    auto db = [](float v, bool sign) { return (sign && v >= 0.0f ? "+" : "") + juce::String(v, 1) + " dB"; };
    cell("input level",    db(meters.levelDb, false),   ui::text);
    cell("vowel gain",     db(meters.vowelGainDb, true), ui::vowel);
    cell("consonant gain", db(meters.consGainDb, true),  ui::cons);
    cell("applied gain",   db(meters.gainDb, true),      ui::text);
}
