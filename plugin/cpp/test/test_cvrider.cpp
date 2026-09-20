// Standalone behavioural tests for the CVRider DSP core (no framework needed).
//   g++ -std=c++17 -O2 -I.. test_cvrider.cpp -o test_cvrider && ./test_cvrider
#include "../CVRider.h"

#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

namespace {

constexpr double kFs = 48000.0;
constexpr int    kBlock = 64;

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
                phase += 2.0 * M_PI * 150.0 / kFs;
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

int main() {
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
        check(r.getLatencySamples() == 240, "5 ms lookahead reports 240 samples latency at 48 kHz");
        std::vector<float> L(1000, 0.f), R(1000, 0.f); L[10] = 1.f; R[10] = -1.f;
        float* ch[2] = { L.data(), R.data() };
        r.process(ch, 2, 1000);
        check(L[250] == 1.f && R[250] == -1.f && L[10] == 0.f, "bypass passes the signal through delayed by the lookahead");
        p.bypass = false; p.vowelRangeDb = 0.f; p.consRangeDb = 0.f; p.outputDb = -6.f;
        r.setParams(p); r.reset();
        std::fill(L.begin(), L.end(), 0.f); std::fill(R.begin(), R.end(), 0.f); L[10] = 1.f; R[10] = 0.5f;
        r.process(ch, 2, 1000);
        check(std::fabs(L[250] - 0.5012f) < 1e-3f && std::fabs(R[250] - 0.2506f) < 1e-3f, "output trim -6 dB applied equally to both channels");
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

    std::printf("\n%s (%d failure%s)\n", g_failures ? "FAILED" : "ALL PASSED", g_failures, g_failures == 1 ? "" : "s");
    return g_failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
