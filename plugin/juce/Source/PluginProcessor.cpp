#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace {
using Range = juce::NormalisableRange<float>;

auto dbRange(float lo, float hi)  { return Range(lo, hi, 0.1f); }
auto msRange(float lo, float hi)  { Range r(lo, hi, 0.1f); r.setSkewForCentre(std::sqrt(lo * hi)); return r; }

juce::String dbText(float v, int)    { return juce::String(v, 1) + " dB"; }
juce::String msText(float v, int)    { return juce::String(v, 1) + " ms"; }
juce::String hzText(float v, int)    { return juce::String(juce::roundToInt(v)) + " Hz"; }

std::unique_ptr<juce::AudioParameterFloat> makeFloat(const char* id, const char* name, Range range, float def,
                                                     juce::String (*text)(float, int)) {
    return std::make_unique<juce::AudioParameterFloat>(
        juce::ParameterID { id, 1 }, name, range, def,
        juce::AudioParameterFloatAttributes().withStringFromValueFunction(text));
}
} // namespace

CVRiderAudioProcessor::CVRiderAudioProcessor()
    : AudioProcessor(BusesProperties()
                         .withInput("Input", juce::AudioChannelSet::stereo(), true)
                         .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      apvts(*this, nullptr, "CVRider", createLayout()) {}

juce::AudioProcessorValueTreeState::ParameterLayout CVRiderAudioProcessor::createLayout() {
    const cvrider::Params d;  // defaults live in the DSP core
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    auto vowel = std::make_unique<juce::AudioProcessorParameterGroup>("vowel", "Vowel", "|");
    vowel->addChild(makeFloat(ParamID::vowelTarget,  "Vowel Target",  dbRange(-40.f, 0.f),   d.vowelTargetDb,  dbText));
    vowel->addChild(makeFloat(ParamID::vowelRange,   "Vowel Range",   dbRange(0.f, 12.f),    d.vowelRangeDb,   dbText));
    vowel->addChild(makeFloat(ParamID::vowelAttack,  "Vowel Attack",  msRange(1.f, 500.f),   d.vowelAttackMs,  msText));
    vowel->addChild(makeFloat(ParamID::vowelRelease, "Vowel Release", msRange(10.f, 2000.f), d.vowelReleaseMs, msText));
    vowel->addChild(makeFloat(ParamID::vowelTrim,    "Vowel Trim",    dbRange(-12.f, 12.f),  d.vowelTrimDb,    dbText));
    layout.add(std::move(vowel));

    auto cons = std::make_unique<juce::AudioProcessorParameterGroup>("consonant", "Consonant", "|");
    cons->addChild(makeFloat(ParamID::consTarget,  "Consonant Target",  dbRange(-40.f, 0.f),  d.consTargetDb,  dbText));
    cons->addChild(makeFloat(ParamID::consRange,   "Consonant Range",   dbRange(0.f, 12.f),   d.consRangeDb,   dbText));
    cons->addChild(makeFloat(ParamID::consAttack,  "Consonant Attack",  msRange(0.1f, 50.f),  d.consAttackMs,  msText));
    cons->addChild(makeFloat(ParamID::consRelease, "Consonant Release", msRange(5.f, 500.f),  d.consReleaseMs, msText));
    cons->addChild(makeFloat(ParamID::consTrim,    "Consonant Trim",    dbRange(-12.f, 12.f), d.consTrimDb,    dbText));
    layout.add(std::move(cons));

    auto det = std::make_unique<juce::AudioProcessorParameterGroup>("detector", "Detector", "|");
    det->addChild(makeFloat(ParamID::sensitivity,   "Sensitivity",    dbRange(-12.f, 12.f),   d.sensitivityDb,   dbText));
    det->addChild(makeFloat(ParamID::splitFreq,     "Split Freq",     msRange(2000.f, 8000.f), d.splitHz,        hzText));
    det->addChild(makeFloat(ParamID::idleThreshold, "Idle Threshold", dbRange(-80.f, -20.f),  d.idleThresholdDb, dbText));
    det->addChild(makeFloat(ParamID::lookahead,     "Lookahead",      Range(0.f, cvrider::detail::kMaxLookaheadMs, 0.1f), d.lookaheadMs, msText));
    layout.add(std::move(det));

    layout.add(makeFloat(ParamID::output, "Output", dbRange(-24.f, 24.f), d.outputDb, dbText));
    layout.add(std::make_unique<juce::AudioParameterChoice>(
        juce::ParameterID { ParamID::monitor, 1 }, "Monitor",
        juce::StringArray { "Off", "Consonants", "Vowels" }, d.monitor));
    layout.add(std::make_unique<juce::AudioParameterBool>(juce::ParameterID { ParamID::bypass, 1 }, "Bypass", d.bypass));
    return layout;
}

cvrider::Params CVRiderAudioProcessor::readParams() const {
    auto get = [this](const char* id) { return apvts.getRawParameterValue(id)->load(); };
    cvrider::Params p;
    p.vowelTargetDb   = get(ParamID::vowelTarget);
    p.vowelRangeDb    = get(ParamID::vowelRange);
    p.vowelAttackMs   = get(ParamID::vowelAttack);
    p.vowelReleaseMs  = get(ParamID::vowelRelease);
    p.vowelTrimDb     = get(ParamID::vowelTrim);
    p.consTargetDb    = get(ParamID::consTarget);
    p.consRangeDb     = get(ParamID::consRange);
    p.consAttackMs    = get(ParamID::consAttack);
    p.consReleaseMs   = get(ParamID::consRelease);
    p.consTrimDb      = get(ParamID::consTrim);
    p.sensitivityDb   = get(ParamID::sensitivity);
    p.splitHz         = get(ParamID::splitFreq);
    p.idleThresholdDb = get(ParamID::idleThreshold);
    p.lookaheadMs     = get(ParamID::lookahead);
    p.outputDb        = get(ParamID::output);
    p.monitor         = juce::roundToInt(get(ParamID::monitor));
    p.bypass          = get(ParamID::bypass) > 0.5f;
    return p;
}

void CVRiderAudioProcessor::prepareToPlay(double sampleRate, int samplesPerBlock) {
    rider.prepare(sampleRate, getTotalNumOutputChannels(), samplesPerBlock);
    rider.setParams(readParams());
    reportedLatency = rider.getLatencySamples();
    setLatencySamples(reportedLatency);
}

bool CVRiderAudioProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const {
    const auto& out = layouts.getMainOutputChannelSet();
    if (out != juce::AudioChannelSet::mono() && out != juce::AudioChannelSet::stereo()) return false;
    return layouts.getMainInputChannelSet() == out;
}

void CVRiderAudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) {
    juce::ScopedNoDenormals noDenormals;
    for (int ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear(ch, 0, buffer.getNumSamples());

    // parameters are cheap to re-read every block (a handful of exp/cos)
    rider.setParams(readParams());
    if (rider.getLatencySamples() != reportedLatency) {
        reportedLatency = rider.getLatencySamples();
        setLatencySamples(reportedLatency);
    }

    rider.process(buffer.getArrayOfWritePointers(), buffer.getNumChannels(), buffer.getNumSamples());
    const auto m = rider.getMeters();
    meterLevel.store(m.levelDb, std::memory_order_relaxed);
    meterProb.store(m.consonantProb, std::memory_order_relaxed);
    meterGv.store(m.vowelGainDb, std::memory_order_relaxed);
    meterGc.store(m.consGainDb, std::memory_order_relaxed);
    meterGain.store(m.gainDb, std::memory_order_relaxed);
}

juce::AudioProcessorEditor* CVRiderAudioProcessor::createEditor() { return new CVRiderAudioProcessorEditor(*this); }

void CVRiderAudioProcessor::getStateInformation(juce::MemoryBlock& destData) {
    if (auto xml = apvts.copyState().createXml()) copyXmlToBinary(*xml, destData);
}

void CVRiderAudioProcessor::setStateInformation(const void* data, int sizeInBytes) {
    if (auto xml = getXmlFromBinary(data, sizeInBytes))
        if (xml->hasTagName(apvts.state.getType())) apvts.replaceState(juce::ValueTree::fromXml(*xml));
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new CVRiderAudioProcessor(); }
