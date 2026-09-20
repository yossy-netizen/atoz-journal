// Standalone behavioural tests for the CVRider DSP core (no framework needed).
//   g++ -std=c++17 -O2 -I.. test_cvrider.cpp -o test_cvrider && ./test_cvrider
#include "../CVRider.h"

#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr int    kBlock = 64;
double kFs = 48000.0;   // set per sample-rate pass in main()

int g_failures = 0;

void check(bool ok, const std::string& what) {
    std::printf("%s  %s\n", ok ? "[ OK ]" : "[FAIL]", what.c_str());
    if (!ok) ++g_failures;
}

// A segment of the synthetic "vocal": kind = 0 silence, 1 vowel (harmonic tone), 2 consonant (white noise)
struct Segment { int kind; double seconds; float rmsDb; };

// Builds a mono test signal and records where each segment starts/ends (in samples).
std::vector<float> makeSignal(const std::vector<Segment>& segs, std::vector<std::pair<int,int>>& bounds) {
    std::vector<float> out;
    std::mt19937 rng(1234);
    std::normal_distribution<float> gauss(0.0f, 1.0f);
    double phase = 0.0;
    for (const auto& s : segs) {
        const int n = static_cast<int>(s.seconds * kFs);
        const int start = static_cast<int>(out.size());
        const float amp = std::pow(10.0f, s.rmsDb / 20.0f);
        for (int i = 0; i < n; ++i) {
            float v = 0.0f;
            if (s.kind == 1) {
                // 8 harmonics of 150 Hz, 1/k amplitude — vowel-like, energy well below 4 kHz
                double sum = 0.0, norm = 0.0;
                for (int k = 1; k <= 8; ++k) { sum += std::sin(k * phase) / k; norm += 1.0 / (2.0 * k * k); }
                v = static_cast<float>(sum / std::sqrt(norm)) * amp;     // unit-RMS tone × amp
                phase += 2.0 * kPi * 150.0 / kFs;
            } else if (s.kind == 2) {
                v = gauss(rng) * amp;                                     // unit-RMS noise × amp
            } else {
                v = gauss(rng) * 1.0e-4f;                                 // -80 dB floor
            }
            out.push_back(v);
        }
        bounds.emplace_back(start, start + n);
    }
    return out;
}

float rmsDb(const std::vector<float>& x, int from, int to) {
    double acc = 0.0;
    for (int i = from; i < to; ++i) acc += double(x[i]) * x[i];
    return static_cast<float>(10.0 * std::log10(acc / std::max(1, to - from) + 1e-20));
}

// Runs the rider block by block; returns output and a per-block trace of the meters.
std::vector<float> run(const std::vector<float>& in, const cvrider::Params& p, std::vector<cvrider::Meters>* trace = nullptr) {
    cvrider::CVRider r;
    r.prepare(kFs, 1, kBlock);
    r.setParams(p);
    std::vector<float> out = in;
    for (int pos = 0; pos < static_cast<int>(out.size()); pos += kBlock) {
        const int n = std::min(kBlock, static_cast<int>(out.size()) - pos);
        float* chans[1] = { out.data() + pos };
        r.process(chans, 1, n);
        if (trace) trace->push_back(r.getMeters());
    }
    return out;
}

float meanProb(const std::vector<cvrider::Meters>& trace, int from, int to) {
    double acc = 0.0; int cnt = 0;
    for (int i = from / kBlock; i < to / kBlock; ++i) { acc += trace[i].consonantProb; ++cnt; }
    return cnt ? static_cast<float>(acc / cnt) : 0.0f;
}

} // namespace

void runSuite();

int main() {
    for (double fs : {44100.0, 48000.0, 96000.0}) {
        kFs = fs;
        std::printf("--- %.0f Hz ---\n", fs);
        runSuite();
    }
    std::printf("\n%s (%d failure%s)\n", g_failures ? "FAILED" : "ALL PASSED", g_failures, g_failures == 1 ? "" : "s");
    return g_failures ? EXIT_FAILURE : EXIT_SUCCESS;
}

void runSuite() {
    std::vector<std::pair<int,int>> b;
    const std::vector<Segment> segs = {
        {0, 0.30, -80.f},   // 0 silence
        {1, 1.00, -30.f},   // 1 quiet vowel
        {2, 0.15, -30.f},   // 2 quiet consonant
        {1, 1.00, -12.f},   // 3 loud vowel
        {2, 0.15, -12.f},   // 4 loud consonant
        {0, 0.30, -80.f},   // 5 silence
    };
    const auto in = makeSignal(segs, b);
    auto mid = [&](int seg, double fromFrac, double toFrac) {
        const int len = b[seg].second - b[seg].first;
        return std::make_pair(b[seg].first + int(len * fromFrac), b[seg].first + int(len * toFrac));
    };

    // ---------------------------------------------------------------- classifier
    {
        cvrider::Params p;  // defaults
        std::vector<cvrider::Meters> tr;
        run(in, p, &tr);
        for (int s : {1, 3}) { auto [f, t] = mid(s, 0.2, 1.0); float c = meanProb(tr, f, t);
            check(c < 0.15f, "vowel segment " + std::to_string(s) + " classified as vowel (c=" + std::to_string(c) + ")"); }
        for (int s : {2, 4}) { auto [f, t] = mid(s, 0.2, 1.0); float c = meanProb(tr, f, t);
            check(c > 0.85f, "consonant segment " + std::to_string(s) + " classified as consonant (c=" + std::to_string(c) + ")"); }
        // reaction time: within the first 10 ms of the consonant, c should already be > 0.5
        { auto [f, t] = mid(2, 0.0, 0.0); float c = tr[(f + int(0.010 * kFs)) / kBlock].consonantProb;
            check(c > 0.5f, "consonant detected within 10 ms (c=" + std::to_string(c) + ")"); }
    }

    // ---------------------------------------------------------------- vowel rider only
    {
        cvrider::Params p;
        p.vowelTargetDb = -18.f; p.vowelRangeDb = 12.f; p.vowelAttackMs = 30.f; p.vowelReleaseMs = 100.f;
        p.consRangeDb = 0.f;
        const auto out = run(in, p);
        { auto [f, t] = mid(1, 0.7, 1.0); float l = rmsDb(out, f, t);
            check(std::fabs(l + 18.f) < 1.5f, "quiet vowel ridden up to -18 dB (got " + std::to_string(l) + ")"); }
        { auto [f, t] = mid(3, 0.7, 1.0); float l = rmsDb(out, f, t);
            check(std::fabs(l + 18.f) < 1.5f, "loud vowel ridden down to -18 dB (got " + std::to_string(l) + ")"); }
        for (int s : {2, 4}) { auto [f, t] = mid(s, 0.3, 1.0);
            float d = rmsDb(out, f, t) - rmsDb(in, f, t);
            check(std::fabs(d) < 1.0f, "consonant segment " + std::to_string(s) + " untouched by vowel rider (delta " + std::to_string(d) + " dB)"); }
    }

    // ---------------------------------------------------------------- consonant rider only
    {
        cvrider::Params p;
        p.vowelRangeDb = 0.f;
        p.consTargetDb = -24.f; p.consRangeDb = 12.f; p.consAttackMs = 2.f; p.consReleaseMs = 20.f;
        const auto out = run(in, p);
        for (int s : {2, 4}) { auto [f, t] = mid(s, 0.4, 1.0); float l = rmsDb(out, f, t);
            check(std::fabs(l + 24.f) < 2.0f, "consonant segment " + std::to_string(s) + " ridden to -24 dB (got " + std::to_string(l) + ")"); }
        for (int s : {1, 3}) { auto [f, t] = mid(s, 0.3, 1.0);
            float d = rmsDb(out, f, t) - rmsDb(in, f, t);
            check(std::fabs(d) < 1.0f, "vowel segment " + std::to_string(s) + " untouched by consonant rider (delta " + std::to_string(d) + " dB)"); }
    }

    // ---------------------------------------------------------------- trims
    {
        cvrider::Params p;
        p.vowelRangeDb = 0.f; p.consRangeDb = 0.f;
        p.vowelTrimDb = 3.f; p.consTrimDb = -6.f;
        const auto out = run(in, p);
        { auto [f, t] = mid(3, 0.3, 1.0); float d = rmsDb(out, f, t) - rmsDb(in, f, t);
            check(std::fabs(d - 3.f) < 0.5f, "vowel trim +3 dB applied to vowels (delta " + std::to_string(d) + ")"); }
        { auto [f, t] = mid(4, 0.3, 1.0); float d = rmsDb(out, f, t) - rmsDb(in, f, t);
            check(std::fabs(d + 6.f) < 0.7f, "consonant trim -6 dB applied to consonants (delta " + std::to_string(d) + ")"); }
    }

    // ---------------------------------------------------------------- idle
    {
        cvrider::Params p;
        p.vowelTargetDb = -18.f; p.vowelRangeDb = 12.f; p.idleThresholdDb = -50.f;
        const auto out = run(in, p);
        auto [f, t] = mid(0, 0.3, 1.0);
        float d = rmsDb(out, f, t) - rmsDb(in, f, t);
        check(std::fabs(d) < 0.5f, "noise floor below idle threshold is not raised (delta " + std::to_string(d) + " dB)");
    }

    // ---------------------------------------------------------------- bypass, lookahead, latency
    {
        cvrider::Params p;
        p.lookaheadMs = 5.f; p.bypass = true;
        cvrider::CVRider r; r.prepare(kFs, 2, kBlock); r.setParams(p);
        const int la = static_cast<int>(std::lround(0.005 * kFs));
        check(r.getLatencySamples() == la, "5 ms lookahead reports " + std::to_string(la) + " samples latency");
        std::vector<float> L(2000, 0.f), R(2000, 0.f); L[10] = 1.f; R[10] = -1.f;
        float* ch[2] = { L.data(), R.data() };
        r.process(ch, 2, 2000);
        check(L[10 + la] == 1.f && R[10 + la] == -1.f && L[10] == 0.f, "bypass passes the signal through delayed by the lookahead");
        p.bypass = false; p.vowelRangeDb = 0.f; p.consRangeDb = 0.f; p.outputDb = -6.f;
        r.setParams(p); r.reset();
        std::fill(L.begin(), L.end(), 0.f); std::fill(R.begin(), R.end(), 0.f); L[10] = 1.f; R[10] = 0.5f;
        r.process(ch, 2, 2000);
        check(std::fabs(L[10 + la] - 0.5012f) < 1e-3f && std::fabs(R[10 + la] - 0.2506f) < 1e-3f, "output trim -6 dB applied equally to both channels");
    }

    // ---------------------------------------------------------------- stereo: same gain on both channels
    {
        cvrider::Params p;
        cvrider::CVRider r; r.prepare(kFs, 2, kBlock); r.setParams(p);
        std::vector<float> L = in, R = in;
        for (auto& v : R) v *= 0.5f;   // right channel 6 dB lower, same content
        for (int pos = 0; pos < static_cast<int>(L.size()); pos += kBlock) {
            const int n = std::min(kBlock, static_cast<int>(L.size()) - pos);
            float* ch[2] = { L.data() + pos, R.data() + pos };
            r.process(ch, 2, n);
        }
        float maxDev = 0.f;
        for (size_t i = 0; i < L.size(); ++i) maxDev = std::max(maxDev, std::fabs(L[i] * 0.5f - R[i]));
        check(maxDev < 1e-5f, "stereo: identical gain applied to both channels (max deviation " + std::to_string(maxDev) + ")");
    }

    // ---------------------------------------------------------------- DC offset does not hide consonants
    {
        cvrider::Params p;
        std::vector<float> dcIn = in;
        for (auto& v : dcIn) v += 0.1f;   // -20 dBFS DC offset
        std::vector<cvrider::Meters> tr;
        run(dcIn, p, &tr);
        auto [f, t] = mid(2, 0.2, 1.0); float c = meanProb(tr, f, t);
        check(c > 0.85f, "consonant still detected with a DC offset present (c=" + std::to_string(c) + ")");
        auto [f2, t2] = mid(1, 0.2, 1.0); float cv = meanProb(tr, f2, t2);
        check(cv < 0.15f, "vowel still classified as vowel with a DC offset present (c=" + std::to_string(cv) + ")");
    }

    // ---------------------------------------------------------------- parameter steps do not click
    {
        // steady loud vowel; jump the output/trim by 12 dB mid-way and look for a sample-to-sample jump
        std::vector<Segment> one = {{1, 0.6, -12.f}};
        std::vector<std::pair<int,int>> bb;
        const auto tone = makeSignal(one, bb);
        cvrider::Params p; p.vowelRangeDb = 0.f; p.consRangeDb = 0.f;
        p.lookaheadMs = 0.f;   // so out[i] / tone[i] is the applied gain
        cvrider::CVRider r; r.prepare(kFs, 1, kBlock); r.setParams(p);
        std::vector<float> out = tone;
        int half = static_cast<int>(out.size() / 2);
        half -= half % kBlock;   // align the step to a block boundary
        for (int pos = 0; pos < static_cast<int>(out.size()); pos += kBlock) {
            if (pos == half) { p.outputDb = 6.f; p.vowelTrimDb = -12.f; p.consTrimDb = 6.f; r.setParams(p); }   // net -6 dB on vowels
            const int n = std::min(kBlock, static_cast<int>(out.size()) - pos);
            float* ch[1] = { out.data() + pos };
            r.process(ch, 1, n);
        }
        // ratio out/in must change smoothly: max step of the gain between neighbouring samples
        float maxStep = 0.f;
        for (int i = half - 200; i < half + 2000; ++i) {
            if (std::fabs(tone[i]) < 0.05f || std::fabs(tone[i - 1]) < 0.05f) continue;
            maxStep = std::max(maxStep, std::fabs(out[i] / tone[i] - out[i - 1] / tone[i - 1]));
        }
        check(maxStep > 0.f && maxStep < 0.02f, "trim/output steps are smoothed (max per-sample gain step " + std::to_string(maxStep) + ")");
        const float endGain = rmsDb(out, static_cast<int>(out.size() * 0.8), static_cast<int>(out.size())) - rmsDb(tone, static_cast<int>(out.size() * 0.8), static_cast<int>(out.size()));
        check(std::fabs(endGain + 6.f) < 0.2f, "trim/output steps settle at the new value (" + std::to_string(endGain) + " dB)");

        // bypass toggle while +6 dB of static gain is applied: the gain must ramp, not jump
        p = cvrider::Params{}; p.vowelRangeDb = 0.f; p.consRangeDb = 0.f; p.lookaheadMs = 0.f; p.outputDb = 6.f;
        r.setParams(p); r.reset();
        out = tone;
        for (int pos = 0; pos < static_cast<int>(out.size()); pos += kBlock) {
            if (pos == half) { p.bypass = true; r.setParams(p); }
            const int n = std::min(kBlock, static_cast<int>(out.size()) - pos);
            float* ch[1] = { out.data() + pos };
            r.process(ch, 1, n);
        }
        maxStep = 0.f;
        for (int i = half - 200; i < half + 2000; ++i) {
            if (std::fabs(tone[i]) < 0.05f || std::fabs(tone[i - 1]) < 0.05f) continue;
            maxStep = std::max(maxStep, std::fabs(out[i] / tone[i] - out[i - 1] / tone[i - 1]));
        }
        check(maxStep > 0.f && maxStep < 0.05f, "bypass toggle is de-clicked (max per-sample gain step " + std::to_string(maxStep) + ")");
        check(std::fabs(out.back() - tone.back()) < 1e-5f, "bypass settles at unity");
    }

    // ---------------------------------------------------------------- no startup ramp after prepare() + setParams()
    {
        // host order: prepare() first, then setParams() with the saved state — the very first samples
        // must already carry the saved Output, not ramp in from the default.
        std::vector<Segment> one = {{1, 0.05, -12.f}};
        std::vector<std::pair<int,int>> bb;
        const auto tone = makeSignal(one, bb);
        cvrider::Params p; p.vowelRangeDb = 0.f; p.consRangeDb = 0.f; p.lookaheadMs = 0.f; p.outputDb = -12.f;
        cvrider::CVRider r; r.prepare(kFs, 1, kBlock); r.setParams(p);
        std::vector<float> out = tone;
        float* ch[1] = { out.data() };
        r.process(ch, 1, kBlock);
        float maxErr = 0.f;
        for (int i = 0; i < kBlock; ++i) maxErr = std::max(maxErr, std::fabs(out[i] - tone[i] * 0.2512f));
        check(maxErr < 1e-3f, "first block after prepare()+setParams() already has the saved output gain (err " + std::to_string(maxErr) + ")");
    }

    // ---------------------------------------------------------------- monitor modes
    {
        cvrider::Params p; p.monitor = 1;
        const auto cons = run(in, p);
        p.monitor = 2;
        const auto vows = run(in, p);
        { auto [f, t] = mid(4, 0.3, 1.0);
            check(rmsDb(cons, f, t) - rmsDb(in, f, t) > -1.f && rmsDb(vows, f, t) < -40.f, "monitor: consonants solo keeps the consonant, vowels solo removes it"); }
        { auto [f, t] = mid(3, 0.3, 1.0);
            check(rmsDb(vows, f, t) - rmsDb(in, f, t) > -1.f && rmsDb(cons, f, t) < -40.f, "monitor: vowels solo keeps the vowel, consonants solo removes it"); }
    }
}
