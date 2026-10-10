import QtQuick
import frontend_v2

// What a setting's `relevantWhen` means, in one place. Two readers act on it:
// SettingsPane HIDES a row while the setting it is nested under fails its rule,
// and SettingRow FADES and disables a row while any other rule fails.
//
// `relevantWhen` is one rule or a list of rules that must ALL hold. A rule either
// names a setting (`key` + `equals` / `notEquals`), which may be in EITHER half,
// so it is resolved via Settings.valueOf rather than Settings.values, which knows
// only local keys — or names a runtime `condition`, resolved against the table in
// conditionHolds().
//
// valueOf is an invokable, which captures no property to depend on, so a binding
// built on these functions must read Settings.valuesRevision itself.
QtObject {
    // The rules as a plain list, whichever form the schema used. A list is told
    // apart by its length, not Array.isArray: it arrives from C++ as a
    // QVariantList, which need not convert to a true JS array.
    function list(rules) {
        if (rules === undefined || rules === null)
            return []
        if (rules.length === undefined)
            return [rules]
        const out = []
        for (let i = 0; i < rules.length; ++i)
            out.push(rules[i])
        return out
    }

    function allHold(rules) {
        for (const rule of list(rules)) {
            if (!ruleHolds(rule))
                return false
        }
        return true
    }

    function ruleHolds(dep) {
        if (dep === undefined || dep === null)
            return true
        if (dep.condition !== undefined)
            return conditionHolds(dep.condition)
        if (dep.key === undefined)
            return true
        const current = Settings.valueOf(dep.key)
        if (dep.equals !== undefined)
            return current === dep.equals
        if (dep.notEquals !== undefined)
            return current !== dep.notEquals
        return true
    }

    // Facts no setting holds. Read straight from their singletons, so a binding
    // that calls this follows them.
    function conditionHolds(name) {
        switch (name) {
        case "screensaverPhotos": return Photos.count > 0
        case "equalizer": return equalizerState() !== "unavailable"
        default: return true
        }
    }

    // The equalizer's runtime state, which the backend carries on the bass row's
    // entry (backend/src/audio_service/CLAUDE.md); "" until a schema has it.
    function equalizerState() {
        const groups = Settings.groups
        for (let i = 0; i < groups.length; ++i) {
            const sections = groups[i].sections !== undefined ? groups[i].sections : []
            for (let j = 0; j < sections.length; ++j) {
                const entries = sections[j].settings !== undefined ? sections[j].settings : []
                for (let k = 0; k < entries.length; ++k) {
                    if (entries[k].key === "audio.bassBoost")
                        return entries[k].runtime !== undefined ? entries[k].runtime.state : ""
                }
            }
        }
        return ""
    }
}
