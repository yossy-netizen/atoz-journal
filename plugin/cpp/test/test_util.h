// Shared helpers for the CVRider behavioural tests: synthetic signals, RMS, block-wise processing.
#pragma once

#include "CVRider.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace testutil {

constexpr double kPi   = 3.14159265358979323846;
constexpr int    kBlock = 64;

inline double g_fs = 48000.0;   // set per sample-rate pass
inline int    g_failures = 0;

inline void check(bool ok, const std::string& what) {
    std::printf("%s  %s\n", ok ? "[ OK ]" : "[FAIL]", what.c_str());
    if (!ok) ++g_failures;
}

inline float rmsDb(const std::vector<float>& x, int from, int to) {
    double acc = 0.0;
    for (int i = from; i < to; ++i) acc += double(x[i]) * x[i];
    return static_cast<float>(10.0 * std::log10(acc / std::max(1, to - from) + 1e-20));
}

// Scales x[from..to) to the given RMS level (dBFS).
inline void normalise(std::vector<float>& x, int from, int to, float targetDb) {
    const float cur = rmsDb(x, from, to);
    const float g = std::pow(10.0f, (targetDb - cur) / 20.0f);
    for (int i = from; i < to; ++i) x[i] *= g;
}

// 2-pole resonator (formant) : H(z) = 1 / (1 - 2 r cosθ z^-1 + r² z^-2)
struct Resonator {
    float a1 = 0, a2 = 0, y1 = 0, y2 = 0;
    void set(double fs, double freq, double bw) {
        const double r = std::exp(-kPi * bw / fs), th = 2.0 * kPi * freq / fs;
        a1 = static_cast<float>(2.0 * r * std::cos(th)); a2 = static_cast<float>(-r * r);
    }
    float process(float x) { const float y = x + a1 * y1 + a2 * y2; y2 = y1; y1 = y; return y; }
};

struct OnePoleLP {
    float k = 0, y = 0;
    void set(double fs, double fc) { k = static_cast<float>(std::exp(-2.0 * kPi * fc / fs)); }
    float process(float x) { y = x + k * (y - x); return y; }
};

struct OnePoleHP {
    OnePoleLP lp;
    void set(double fs, double fc) { lp.set(fs, fc); }
    float process(float x) { return x - lp.process(x); }
};

// Formant-synthesised vowel: glottal pulse train (−6 dB/oct source tilt) through 3 resonators.
// Returns unit-RMS-ish samples; caller normalises.
inline std::vector<float> vowel(double fs, int n, double f0, double f1, double f2, double f3) {
    std::vector<float> out(static_cast<size_t>(n));
    Resonator r1, r2, r3; r1.set(fs, f1, 80.0); r2.set(fs, f2, 100.0); r3.set(fs, f3, 140.0);
    OnePoleLP tilt; tilt.set(fs, 500.0);
    double phase = 0.0;
    for (int i = 0; i < n; ++i) {
        phase += f0 / fs;
        float src = 0.0f;
        if (phase >= 1.0) { phase -= 1.0; src = 1.0f; }
        out[static_cast<size_t>(i)] = r3.process(r2.process(r1.process(tilt.process(src))));
    }
    return out;
}

// Gaussian noise, optionally high-passed (sibilant "s") or band-passed ("sh").
inline std::vector<float> noise(double fs, int n, std::mt19937& rng, double hpHz = 0.0, double lpHz = 0.0) {
    std::normal_distribution<float> gauss(0.0f, 1.0f);
    std::vector<float> out(static_cast<size_t>(n));
    OnePoleHP hp1, hp2; OnePoleLP lp1, lp2;
    if (hpHz > 0) { hp1.set(fs, hpHz); hp2.set(fs, hpHz); }
    if (lpHz > 0) { lp1.set(fs, lpHz); lp2.set(fs, lpHz); }
    for (int i = 0; i < n; ++i) {
        float v = gauss(rng);
        if (hpHz > 0) v = hp2.process(hp1.process(v));
        if (lpHz > 0) v = lp2.process(lp1.process(v));
        out[static_cast<size_t>(i)] = v;
    }
    return out;
}

// A segment of the classic synthetic "vocal": kind = 0 silence, 1 harmonic tone, 2 white noise
struct Segment { int kind; double seconds; float rmsDb; };

inline std::vector<float> makeSignal(const std::vector<Segment>& segs, std::vector<std::pair<int,int>>& bounds) {
    std::vector<float> out;
    std::mt19937 rng(1234);
    std::normal_distribution<float> gauss(0.0f, 1.0f);
    double phase = 0.0;
    for (const auto& s : segs) {
        const int n = static_cast<int>(s.seconds * g_fs);
        const int start = static_cast<int>(out.size());
        const float amp = std::pow(10.0f, s.rmsDb / 20.0f);
        for (int i = 0; i < n; ++i) {
            float v = 0.0f;
            if (s.kind == 1) {
                double sum = 0.0, norm = 0.0;
                for (int k = 1; k <= 8; ++k) { sum += std::sin(k * phase) / k; norm += 1.0 / (2.0 * k * k); }
                v = static_cast<float>(sum / std::sqrt(norm)) * amp;
                phase += 2.0 * kPi * 150.0 / g_fs;
            } else if (s.kind == 2) {
                v = gauss(rng) * amp;
            } else {
                v = gauss(rng) * 1.0e-4f;
            }
            out.push_back(v);
        }
        bounds.emplace_back(start, start + n);
    }
    return out;
}

// Runs the rider block by block; returns output and a per-block trace of the meters.
inline std::vector<float> run(const std::vector<float>& in, const cvrider::Params& p, std::vector<cvrider::Meters>* trace = nullptr, int channels = 1) {
    cvrider::CVRider r;
    r.prepare(g_fs, channels, kBlock);
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

inline float meanProb(const std::vector<cvrider::Meters>& trace, int from, int to) {
    double acc = 0.0; int cnt = 0;
    for (int i = from / kBlock; i < to / kBlock && i < static_cast<int>(trace.size()); ++i) { acc += trace[static_cast<size_t>(i)].consonantProb; ++cnt; }
    return cnt ? static_cast<float>(acc / cnt) : 0.0f;
}

inline float maxProb(const std::vector<cvrider::Meters>& trace, int from, int to) {
    float m = 0.0f;
    for (int i = from / kBlock; i < to / kBlock && i < static_cast<int>(trace.size()); ++i) m = std::max(m, trace[static_cast<size_t>(i)].consonantProb);
    return m;
}

} // namespace testutil
