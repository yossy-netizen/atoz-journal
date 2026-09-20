// Presets.h — factory presets for CV Rider (shared by the JUCE plugin; mirrored in web/index.html)
#pragma once

#include "CVRider.h"

#include <vector>

namespace cvrider {

struct Preset {
    const char* name;
    Params params;
};

inline const std::vector<Preset>& presets() {
    static const std::vector<Preset> list = [] {
        std::vector<Preset> v;
        auto add = [&v](const char* name, auto&& fn) { Params p; fn(p); v.push_back({ name, p }); };

        add("Default", [](Params&) {});

        // Everyday pop / rock lead: firm vowel ride, consonants slightly tamed
        add("Lead Vocal", [](Params& p) {
            p.vowelTargetDb = -18.f; p.vowelRangeDb = 8.f;  p.vowelAttackMs = 40.f;  p.vowelReleaseMs = 250.f;
            p.consTargetDb  = -24.f; p.consRangeDb  = 8.f;  p.consAttackMs  = 1.5f;  p.consReleaseMs  = 40.f;  p.consTrimDb = -1.f;
        });

        // Light touch for already well-performed takes
        add("Gentle", [](Params& p) {
            p.vowelRangeDb = 4.f; p.vowelAttackMs = 100.f; p.vowelReleaseMs = 500.f;
            p.consRangeDb  = 3.f; p.consAttackMs  = 3.f;   p.consReleaseMs  = 60.f;
        });

        // Only the consonant rider works: a de-esser that also evens out weak consonants
        add("De-ess Only", [](Params& p) {
            p.vowelRangeDb = 0.f;
            p.consTargetDb = -26.f; p.consRangeDb = 10.f; p.consAttackMs = 1.f; p.consReleaseMs = 30.f; p.consTrimDb = -2.f;
            p.sensitivityDb = 2.f;
        });

        // Bring up soft consonants for intelligibility (mumbly singer, dense mix)
        add("Clarity", [](Params& p) {
            p.vowelRangeDb = 3.f;
            p.consTargetDb = -18.f; p.consRangeDb = 8.f; p.consTrimDb = 2.f;
        });

        // Breathy / whisper vocals: breath noise is not treated as consonant
        add("Breathy", [](Params& p) {
            p.sensitivityDb = -4.f; p.splitHz = 5000.f;
            p.vowelTargetDb = -20.f; p.vowelRangeDb = 6.f; p.vowelAttackMs = 80.f; p.vowelReleaseMs = 400.f;
            p.consRangeDb = 4.f;
        });

        // Spoken word / narration: wider vowel range, consonants kept clearly under the voice
        add("Narration", [](Params& p) {
            p.vowelTargetDb = -20.f; p.vowelRangeDb = 10.f; p.vowelAttackMs = 30.f; p.vowelReleaseMs = 200.f;
            p.consTargetDb  = -26.f; p.consRangeDb  = 8.f;
        });
        return v;
    }();
    return list;
}

} // namespace cvrider
