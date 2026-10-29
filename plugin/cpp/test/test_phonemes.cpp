// Phoneme-like signals: formant vowels (male / female), sibilants, weak fricatives, plosive bursts,
// breathy vowels. Checks that the classifier's default thresholds separate them.
//   g++ -std=c++17 -O2 -I.. test_phonemes.cpp -o test_phonemes && ./test_phonemes
#include "test_util.h"

using namespace testutil;

namespace {

struct Phone { std::string name; std::vector<float> samples; bool consonant; float minC, maxC; };

// Appends `p` (normalised to levelDb) to `sig` with silence padding; returns [start, end)
std::pair<int,int> append(std::vector<float>& sig, std::vector<float> p, float levelDb, double padSec = 0.25) {
    std::mt19937 rng(7);
    std::normal_distribution<float> gauss(0.0f, 1.0f);
    const int pad = static_cast<int>(padSec * g_fs);
    for (int i = 0; i < pad; ++i) sig.push_back(gauss(rng) * 1.0e-4f);
    normalise(p, 0, static_cast<int>(p.size()), levelDb);
    const int start = static_cast<int>(sig.size());
    sig.insert(sig.end(), p.begin(), p.end());
    return { start, static_cast<int>(sig.size()) };
}

void runSuite() {
    std::mt19937 rng(42);
    const int n = static_cast<int>(0.4 * g_fs);
    cvrider::Params p;   // defaults

    // ---- vowels: c must stay low (mean over the steady part)
    struct V { const char* name; double f0, f1, f2, f3; };
    const V vowels[] = {
        { "/a/ male 120 Hz",   120, 700, 1200, 2600 }, { "/a/ female 240 Hz", 240, 850, 1250, 2850 },
        { "/i/ male 120 Hz",   120, 300, 2300, 3000 }, { "/i/ female 240 Hz", 240, 350, 2700, 3300 },
        { "/u/ male 120 Hz",   120, 300,  900, 2300 }, { "/u/ female 240 Hz", 240, 370,  950, 2650 },
        { "/e/ female 300 Hz", 300, 500, 2300, 3000 },
    };
    for (const auto& v : vowels) {
        std::vector<float> sig; std::vector<cvrider::Meters> tr;
        auto [f, t] = append(sig, vowel(g_fs, n, v.f0, v.f1, v.f2, v.f3), -18.f);
        run(sig, p, &tr);
        const float c = meanProb(tr, f + n / 4, t);
        check(c < 0.2f, std::string("vowel ") + v.name + " stays vowel (c=" + std::to_string(c) + ")");
    }

    // ---- breathy vowel: vowel + broadband noise 15 dB below
    {
        auto v = vowel(g_fs, n, 200, 600, 1700, 2600); normalise(v, 0, n, -18.f);
        auto nz = noise(g_fs, n, rng);            normalise(nz, 0, n, -33.f);
        for (int i = 0; i < n; ++i) v[static_cast<size_t>(i)] += nz[static_cast<size_t>(i)];
        std::vector<float> sig; std::vector<cvrider::Meters> tr;
        auto [f, t] = append(sig, v, -18.f);
        run(sig, p, &tr);
        const float c = meanProb(tr, f + n / 4, t);
        check(c < 0.3f, "breathy vowel (noise -15 dB) stays vowel (c=" + std::to_string(c) + ")");
    }

    // ---- sibilants and fricatives: c must be high
    struct F { const char* name; double hp, lp; float minC; };
    const F frics[] = {
        { "/s/ (noise > 5 kHz)",        5000, 0,    0.9f },
        { "/sh/ (noise 2.5-7 kHz)",     2500, 7000, 0.7f },
        { "/f/ (weak flat noise)",      1000, 0,    0.8f },
        { "/h/ (broadband noise)",      0,    0,    0.8f },
    };
    for (const auto& fr : frics) {
        std::vector<float> sig; std::vector<cvrider::Meters> tr;
        auto [f, t] = append(sig, noise(g_fs, n / 2, rng, fr.hp, fr.lp), -24.f);
        run(sig, p, &tr);
        const float c = meanProb(tr, f + n / 8, t);
        check(c > fr.minC, std::string("fricative ") + fr.name + " detected (c=" + std::to_string(c) + ")");
    }

    // ---- plosive: 12 ms broadband burst right before a vowel, both at -18 dB
    {
        const int burst = static_cast<int>(0.012 * g_fs);
        auto b = noise(g_fs, burst, rng, 1500, 0); normalise(b, 0, burst, -18.f);
        auto v = vowel(g_fs, n, 130, 650, 1100, 2500); normalise(v, 0, n, -18.f);
        std::vector<float> phone = b; phone.insert(phone.end(), v.begin(), v.end());
        std::vector<float> sig; std::vector<cvrider::Meters> tr;
        auto [f, t] = append(sig, phone, -18.f);
        run(sig, p, &tr);
        const float cBurst = maxProb(tr, f, f + burst + kBlock);
        const float cVowel = meanProb(tr, f + burst + n / 4, t);
        check(cBurst > 0.6f, "plosive /t/ burst detected as consonant (peak c=" + std::to_string(cBurst) + ")");
        check(cVowel < 0.2f, "vowel after the burst returns to vowel (c=" + std::to_string(cVowel) + ")");
    }

    // ---- word-like sequence: "sa" "shi" "su" — each consonant ridden to -24, each vowel to -18
    {
        cvrider::Params q; q.vowelTargetDb = -18.f; q.vowelRangeDb = 12.f; q.vowelAttackMs = 20.f; q.vowelReleaseMs = 80.f;
        q.consTargetDb = -24.f; q.consRangeDb = 12.f; q.consAttackMs = 1.f; q.consReleaseMs = 20.f;
        std::vector<float> sig;
        std::vector<std::pair<int,int>> cons, vow;
        auto word = [&](double hp, double lp, double f0, double f1, double f2, double f3) {
            auto c = noise(g_fs, static_cast<int>(0.12 * g_fs), rng, hp, lp); normalise(c, 0, static_cast<int>(c.size()), -12.f);
            auto v = vowel(g_fs, static_cast<int>(0.35 * g_fs), f0, f1, f2, f3);  normalise(v, 0, static_cast<int>(v.size()), -30.f);
            const int s0 = static_cast<int>(sig.size());
            sig.insert(sig.end(), c.begin(), c.end());
            const int s1 = static_cast<int>(sig.size());
            sig.insert(sig.end(), v.begin(), v.end());
            cons.emplace_back(s0, s1); vow.emplace_back(s1, static_cast<int>(sig.size()));
        };
        word(5000, 0, 130, 700, 1200, 2600);    // sa
        word(2500, 7000, 130, 300, 2300, 3000); // shi
        word(5000, 0, 130, 300, 900, 2300);     // su
        const auto out = run(sig, q);
        for (size_t i = 0; i < cons.size(); ++i) {
            const auto [f, t] = cons[i];
            const float l = rmsDb(out, f + (t - f) / 3, t);
            check(std::fabs(l + 24.f) < 2.5f, "word " + std::to_string(i) + ": loud consonant (-12) ridden to -24 (got " + std::to_string(l) + ")");
        }
        for (size_t i = 0; i < vow.size(); ++i) {
            const auto [f, t] = vow[i];
            const float l = rmsDb(out, f + (t - f) / 2, t);
            check(std::fabs(l + 18.f) < 2.5f, "word " + std::to_string(i) + ": quiet vowel (-30) ridden to -18 (got " + std::to_string(l) + ")");
        }
    }
}

} // namespace

int main() {
    for (double fs : { 44100.0, 48000.0, 96000.0 }) {
        g_fs = fs;
        std::printf("--- %.0f Hz ---\n", fs);
        runSuite();
    }
    std::printf("\n%s (%d failure%s)\n", g_failures ? "FAILED" : "ALL PASSED", g_failures, g_failures == 1 ? "" : "s");
    return g_failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
