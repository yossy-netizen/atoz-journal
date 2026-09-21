// CVRider.h — Consonant / Vowel Rider DSP core
//
// Header-only, dependency-free (C++17). This is the single source of truth for
// the algorithm; the JUCE wrapper (../juce) and the Web Audio port (../web)
// are thin shells around the same signal flow.
//
// Signal flow (per sample):
//
//   in ──┬─► lookahead delay ─────────────────────────────► × gain ─► out
//        │
//        └─► detector (mono mix)
//              ├─ HP band (split freq) ──► hf energy ─┐
//              ├─ full band ─────────────► total energy┴─► band ratio ─┐
//              ├─ HP band fast/slow env ─► transient score ────────────┴─► c (consonant probability, 0..1)
//              ├─ slow RMS (vowel)   ──► vowel rider   gv = clamp(targetV − Lv, ±rangeV)  + trimV
//              └─ fast RMS (consonant) ► consonant rider gc = clamp(targetC − Lc, ±rangeC) + trimC
//
//   gain(dB) = c·gc + (1−c)·gv + output
//
// The vowel rider is *held* while a consonant is detected (its smoothing rate is
// scaled by 1−c), so a loud "s" does not drag the vowel gain down.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace cvrider {

struct Params {
    // ---- Vowel rider ----
    float vowelTargetDb  = -18.0f;  // level the vowels are ridden towards (dBFS RMS)
    float vowelRangeDb   = 6.0f;    // max ± gain the vowel rider may apply
    float vowelAttackMs  = 60.0f;   // speed when gain goes DOWN (level above target)
    float vowelReleaseMs = 300.0f;  // speed when gain goes UP   (level below target)
    float vowelTrimDb    = 0.0f;    // static offset applied to vowels only
    // ---- Consonant rider ----
    float consTargetDb   = -24.0f;
    float consRangeDb    = 6.0f;
    float consAttackMs   = 2.0f;
    float consReleaseMs  = 40.0f;
    float consTrimDb     = 0.0f;
    // ---- Detector ----
    float sensitivityDb   = 0.0f;    // + = more of the signal is treated as consonant
    float splitHz         = 4000.0f; // high-pass cutoff of the consonant band
    float idleThresholdDb = -50.0f;  // below this (RMS) both riders return to 0 dB
    float lookaheadMs     = 3.0f;    // audio delay so the gain can precede a consonant
    // ---- Global ----
    float outputDb = 0.0f;
    int   monitor  = 0;              // 0 = normal, 1 = consonants only, 2 = vowels only
    bool  bypass   = false;
};

struct Meters {
    float levelDb       = -120.0f;  // fast RMS level of the detector signal
    float consonantProb = 0.0f;     // smoothed c (0..1)
    float vowelGainDb   = 0.0f;
    float consGainDb    = 0.0f;
    float gainDb        = 0.0f;     // gain actually applied (incl. output)
};

namespace detail {

constexpr float  kMaxLookaheadMs = 10.0f;
constexpr float  kEps            = 1.0e-12f;   // floor inside log10
constexpr float  kAntiDenormal   = 1.0e-20f;   // keeps decaying energy envelopes out of the denormal range
constexpr float  kAntiDenormalIn = 1.0e-18f;   // alternating-sign offset at the detector input (filter states)
constexpr double kPi             = 3.14159265358979323846;

inline float dbToLin(float db) { return std::pow(10.0f, db * 0.05f); }
inline float powToDb(float p)  { return 10.0f * std::log10(p + kEps); }
// 0 below `lo`, 1 above `hi`, smooth in between
inline float smoothstep(float lo, float hi, float x) {
    const float t = std::clamp((x - lo) / (hi - lo), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

// one-pole coefficient for a time constant given in milliseconds
inline float tauCoef(double ms, double fs) {
    if (ms <= 0.0) return 0.0f;
    return static_cast<float>(std::exp(-1.0 / (ms * 0.001 * fs)));
}

// 2nd-order high-pass (RBJ cookbook), transposed direct form II
class BiquadHP {
public:
    void set(double fs, double fc, double q = 0.70710678) {
        fc = std::clamp(fc, 20.0, fs * 0.45);
        const double w0 = 2.0 * kPi * fc / fs;
        const double c  = std::cos(w0);
        const double a  = std::sin(w0) / (2.0 * q);
        const double a0 = 1.0 + a;
        b0 = static_cast<float>((1.0 + c) * 0.5 / a0);
        b1 = static_cast<float>(-(1.0 + c) / a0);
        b2 = b0;
        a1 = static_cast<float>(-2.0 * c / a0);
        a2 = static_cast<float>((1.0 - a) / a0);
    }
    void reset() { z1 = z2 = 0.0f; }
    inline float process(float x) {
        const float y = b0 * x + z1;
        z1 = b1 * x - a1 * y + z2;
        z2 = b2 * x - a2 * y;
        return y;
    }
private:
    float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    float z1 = 0, z2 = 0;
};

// first-order DC blocker (~20 Hz) for the detector path, so a DC offset does not
// inflate the "total" energy and hide consonants
struct DcBlocker {
    float r = 0.999f, x1 = 0.0f, y1 = 0.0f;
    void set(double fs) { r = static_cast<float>(1.0 - 2.0 * kPi * 20.0 / fs); }
    void reset() { x1 = y1 = 0.0f; }
    inline float process(float x) { const float y = x - x1 + r * y1; x1 = x; y1 = y; return y; }
};

// one-pole smoother with separate rise / fall coefficients
struct AsymSmoother {
    float rise = 0, fall = 0, y = 0;
    inline float process(float x) {
        const float k = (x > y) ? rise : fall;
        y = x + k * (y - x);
        return y;
    }
    // same, but the smoothing rate is scaled (0 = hold, 1 = normal)
    inline float process(float x, float rate) {
        const float k0 = (x > y) ? rise : fall;
        const float k  = 1.0f - rate * (1.0f - k0);
        y = x + k * (y - x);
        return y;
    }
};

} // namespace detail

class CVRider {
public:
    void prepare(double sampleRate, int numChannels, int /*maxBlockSize*/) {
        fs = sampleRate;
        channels = std::max(1, numChannels);
        maxDelay = static_cast<int>(std::ceil(detail::kMaxLookaheadMs * 0.001 * fs)) + 1;
        delay.assign(static_cast<size_t>(channels), std::vector<float>(static_cast<size_t>(maxDelay), 0.0f));
        setParams(params);
        reset();
    }

    void reset() {
        dc.reset();
        hp.reset();
        hfEnv = totEnv = hfFast = hfSlow = 0.0f;
        lvEnv = lcEnv = 0.0f;
        lvDbPrev = -120.0f;
        cSmooth.y = 0.0f;
        gvSmooth.y = gcSmooth.y = 0.0f;
        snapPending = true;   // smoothers jump to the current parameters on the next processed sample
        for (auto& d : delay) std::fill(d.begin(), d.end(), 0.0f);
        writePos = 0;
        meters = Meters{};
    }

    void setParams(const Params& p) {
        params = p;
        if (fs <= 0.0) return;
        using namespace detail;
        dc.set(fs);
        hp.set(fs, p.splitHz);
        // static offsets (trims / output) are smoothed over ~10 ms so automation does not click;
        // the final linear gain gets a short ~1 ms smoother that also de-clicks bypass / monitor / range steps
        kOffset = tauCoef(10.0, fs);
        kGain   = tauCoef(1.0, fs);
        // energy envelopes for the band ratio (~6 ms) — short enough for a "t",
        // long enough not to ripple within a pitch period.
        kEnergy = tauCoef(6.0, fs);
        // transient detection inside the consonant band
        kHfFastRise = tauCoef(0.5, fs);  kHfFastFall = tauCoef(5.0, fs);
        kHfSlow     = tauCoef(30.0, fs);
        // level detectors: slow for vowels, fast for consonants
        kLv = tauCoef(40.0, fs);
        kLc = tauCoef(5.0, fs);
        // consonant probability smoothing
        cSmooth.rise = tauCoef(1.0, fs);
        cSmooth.fall = tauCoef(20.0, fs);
        // riders: "attack" = gain going down, "release" = gain going up
        gvSmooth.fall = tauCoef(p.vowelAttackMs, fs);
        gvSmooth.rise = tauCoef(p.vowelReleaseMs, fs);
        gcSmooth.fall = tauCoef(p.consAttackMs, fs);
        gcSmooth.rise = tauCoef(p.consReleaseMs, fs);
        // band-ratio threshold. Vowels sit around −20…−30 dB, sibilants around 0 dB.
        ratioThresholdDb = -9.0f - p.sensitivityDb;
        lookaheadSamples = std::clamp(static_cast<int>(std::lround(p.lookaheadMs * 0.001 * fs)), 0, maxDelay - 1);
    }

    const Params& getParams() const { return params; }
    int getLatencySamples() const { return lookaheadSamples; }
    Meters getMeters() const { return meters; }

    // In-place processing. `buffers[ch][i]`, all channels get the same gain.
    void process(float* const* buffers, int numChannels, int numSamples) {
        using namespace detail;
        numChannels = std::min(numChannels, channels);
        if (numChannels <= 0 || numSamples <= 0) return;

        const float invCh = 1.0f / static_cast<float>(numChannels);
        const float thr = ratioThresholdDb;

        if (snapPending) {
            // first sample after prepare()/reset(): start from the current parameters, not from a ramp
            vowelTrimSm = params.vowelTrimDb;
            consTrimSm  = params.consTrimDb;
            outputSm    = params.outputDb;
            gainSm      = params.bypass ? 1.0f : (params.monitor != 0 ? 0.0f : dbToLin(vowelTrimSm + outputSm));
            snapPending = false;
        }

        for (int i = 0; i < numSamples; ++i) {
            // ---- detector input: mono mix of the *undelayed* signal ----
            float x = 0.0f;
            for (int ch = 0; ch < numChannels; ++ch) x += buffers[ch][i];
            // a tiny alternating offset keeps the recursive filter states out of the denormal range
            ditherSign = -ditherSign;
            x = dc.process(x * invCh + ditherSign * kAntiDenormalIn);

            // ---- consonant classification ----
            const float h  = hp.process(x);
            const float h2 = h * h + kAntiDenormal;   // and the same for the energy envelopes
            const float x2 = x * x + kAntiDenormal;
            hfEnv  = h2 + kEnergy * (hfEnv - h2);
            totEnv = x2 + kEnergy * (totEnv - x2);
            const float ratioDb = powToDb(hfEnv) - powToDb(totEnv);           // ≤ 0 dB
            const float sib     = smoothstep(thr - 4.0f, thr + 4.0f, ratioDb);

            hfFast = h2 + ((h2 > hfFast) ? kHfFastRise : kHfFastFall) * (hfFast - h2);
            hfSlow = h2 + kHfSlow * (hfSlow - h2);
            const float transDb = powToDb(hfFast) - powToDb(hfSlow);
            // a transient only counts if the band ratio is "consonant-ish" (within 8 dB of the threshold)
            const float trans   = smoothstep(5.0f, 11.0f, transDb)
                                * smoothstep(thr - 12.0f, thr - 4.0f, ratioDb);

            // ---- level detectors ----
            lcEnv = x2 + kLc * (lcEnv - x2);
            const float lcDb = powToDb(lcEnv);
            const bool  idle = lcDb < params.idleThresholdDb && lvDbPrev < params.idleThresholdDb;

            // below the idle threshold the (broadband) noise floor must not count as a consonant
            const float c = cSmooth.process(idle ? 0.0f : std::max(sib, trans));

            // the vowel level detector is frozen while a consonant is present, so a loud "s" does not
            // inflate the vowel level for the next ~150 ms (it would otherwise under-boost the vowel)
            {
                const float rate = idle ? 1.0f : 1.0f - c;
                lvEnv += rate * (1.0f - kLv) * (x2 - lvEnv);
            }
            const float lvDb = powToDb(lvEnv);
            lvDbPrev = lvDb;

            // ---- riders ----
            float gvTarget = 0.0f, gcTarget = 0.0f;
            if (!idle) {
                gvTarget = std::clamp(params.vowelTargetDb - lvDb, -params.vowelRangeDb, params.vowelRangeDb);
                gcTarget = std::clamp(params.consTargetDb  - lcDb, -params.consRangeDb,  params.consRangeDb);
            }
            // vowel gain is held while a consonant is detected; when idle it returns to 0 dB normally
            const float gv = gvSmooth.process(gvTarget, idle ? 1.0f : 1.0f - c);
            const float gc = gcSmooth.process(gcTarget);

            // smoothed static offsets
            vowelTrimSm = params.vowelTrimDb + kOffset * (vowelTrimSm - params.vowelTrimDb);
            consTrimSm  = params.consTrimDb  + kOffset * (consTrimSm  - params.consTrimDb);
            outputSm    = params.outputDb    + kOffset * (outputSm    - params.outputDb);

            const float gainDb = c * (gc + consTrimSm) + (1.0f - c) * (gv + vowelTrimSm);
            float gainTarget = dbToLin(gainDb + outputSm);
            if (params.bypass)            gainTarget = 1.0f;
            else if (params.monitor == 1) gainTarget = c;
            else if (params.monitor == 2) gainTarget = 1.0f - c;
            gainSm = gainTarget + kGain * (gainSm - gainTarget);

            // ---- audio path: lookahead delay, then gain ----
            const int readPos = writePos - lookaheadSamples + maxDelay;
            for (int ch = 0; ch < numChannels; ++ch) {
                auto& d = delay[static_cast<size_t>(ch)];
                d[static_cast<size_t>(writePos)] = buffers[ch][i];
                buffers[ch][i] = d[static_cast<size_t>(readPos % maxDelay)] * gainSm;
            }
            if (++writePos >= maxDelay) writePos = 0;

            if (i == numSamples - 1) {
                meters.levelDb       = lcDb;
                meters.consonantProb = c;
                meters.vowelGainDb   = gv + vowelTrimSm;
                meters.consGainDb    = gc + consTrimSm;
                meters.gainDb        = params.bypass ? 0.0f : gainDb + outputSm;
            }
        }
    }

private:
    Params params;
    Meters meters;
    double fs = 0.0;
    int channels = 1;

    detail::DcBlocker dc;
    detail::BiquadHP hp;
    float kEnergy = 0, kHfFastRise = 0, kHfFastFall = 0, kHfSlow = 0, kLv = 0, kLc = 0, kOffset = 0;
    float hfEnv = 0, totEnv = 0, hfFast = 0, hfSlow = 0, lvEnv = 0, lcEnv = 0, lvDbPrev = -120.0f;
    float ratioThresholdDb = -9.0f;
    float kGain = 0;
    float vowelTrimSm = 0, consTrimSm = 0, outputSm = 0, gainSm = 1.0f;
    float ditherSign = 1.0f;
    bool  snapPending = true;
    detail::AsymSmoother cSmooth, gvSmooth, gcSmooth;

    std::vector<std::vector<float>> delay;
    int maxDelay = 1, writePos = 0, lookaheadSamples = 0;
};

} // namespace cvrider
