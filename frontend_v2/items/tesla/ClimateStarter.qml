import QtQuick
import frontend_v2

// HVAC power button: a solid coloured disc icon plus a coloured glow behind it,
// both driven by the HVAC power-state string; a click toggles climate.
//
// The glow is a "breathing" state indicator with a DEFERRED colour/icon swap:
//   * In a settled on/off state the glow is held STEADY at full strength.
//   * The moment the user clicks, the state flips to the pending sentinel and
//     the glow starts BREATHING (opacity oscillates 0 <-> full) in yellow.
//   * When the state resolves (or changes again) the rendered glow colour and
//     disc icon do NOT swap immediately. The swap is DEFERRED to the next
//     breathing TROUGH — the instant the glow is fully invisible — after a
//     brief hold there. So a change rides out the current breath, swaps colour
//     + icon while hidden, then fades back in with the new colour.
//
// The disc icon itself stays fully opaque throughout; only the glow's opacity
// breathes. That works because GlowIcon's MultiEffect renders a single item
// holding both a copy of the source image AND its drop shadow, and
// MultiEffect.shadowOpacity dims ONLY the shadow. So animating the value bound to
// GlowIcon.glowStrength (-> shadowOpacity) fades just the glow; the disc is
// untouched. Colour = GlowIcon.glow (-> shadowColor); disc = GlowIcon.source.
// Both are read from the private `render` object so they only ever change inside
// the trough ScriptAction, never mid-fade.
Item {
    id: starter

    property string powerState: ""
    property int iconSize: 100
    // Gated by the owning view: while the dashboard is hidden the breath must not
    // run (wasted off-screen animation). The re-arm guards below stop it cycling
    // when false; becoming true again resumes breathing if the state still needs
    // it. A breath already in flight rides out its current cycle, then settles.
    property bool isCurrent: true
    onIsCurrentChanged: if (isCurrent) ensureBreathing()
    signal clicked()

    // --- Target state (derived from powerState) ------------------------------
    // What the glow SHOULD become. These update instantly on powerState changes
    // but are NOT shown until the next trough commits them into `render`.
    readonly property bool targetPending:
        powerState !== "HvacPowerStateOn" && powerState !== "HvacPowerStateOff"

    readonly property url targetSource:
        powerState === "HvacPowerStateOn" ? "qrc:/resources/icons/power_on.svg"
        : powerState === "HvacPowerStateOff" ? "qrc:/resources/icons/power_off.svg"
        : "qrc:/resources/icons/power_pending.svg"

    readonly property color targetGlow:
        powerState === "HvacPowerStateOn" ? Theme.glowOn
        : powerState === "HvacPowerStateOff" ? Theme.glowOff
        : Theme.glowPending

    // Peak glow strength (MultiEffect.shadowOpacity at the top of a breath, and
    // the steady rest value). The PENDING glow breathes BRIGHTER than the settled
    // on/off states: each fade-in latches this when it starts, so pending pulses
    // peak at full 1.0 while a resolved/steady glow rests at 0.85. Read only
    // outside powerState's change handler (commit / animation / onCompleted), so
    // the one-transition binding lag that the callLater above guards against
    // cannot affect it.
    readonly property real fullStrength: targetPending ? 1.0 : 0.85

    // --- Private internal state ---------------------------------------------
    // Held in a QtObject so it does not look like a public input. `render.*` is
    // the CURRENTLY rendered glow; `breath` is the live shadow-opacity value.
    QtObject {
        id: render

        // Rendered glow colour + disc icon. Bound into GlowIcon below. Only the
        // trough ScriptAction (commit) writes these, so the visible colour/icon
        // never changes except while the glow is fully hidden.
        property color glow: starter.targetGlow
        property url source: starter.targetSource

        // Live glow opacity (0 = hidden trough, fullStrength = fully shown).
        // Bound into GlowIcon.glowStrength. The breath animation drives it; when
        // settled steady it simply rests at fullStrength.
        property real breath: starter.fullStrength

        // True once the first real powerState has been committed. Guards the
        // cold-start case where powerState is "" then a real value arrives.
        property bool initialised: false

        // Latched true in Component.onCompleted. Until then ensureBreathing() is
        // inert, so the ONLY thing that can start a breath (or touch `breath`)
        // during construction is the controlled cold-start path below. This
        // makes the component robust to QML init ordering: even if a bound
        // powerState fires onPowerStateChanged before onCompleted, it cannot
        // start an animation that onCompleted would then fight by writing breath.
        property bool ready: false
    }

    Component.onCompleted: {
        // Cold start: adopt the first target immediately as the steady rendered
        // state (no startup fade), then let any later change breathe. If the
        // first real value differs from the placeholder default this still
        // converges because ensureBreathing() re-checks against the target.
        commitTarget()
        render.breath = starter.fullStrength
        render.ready = true
        ensureBreathing()
    }

    // Any powerState change re-evaluates whether to breathe. We never touch the
    // rendered colour/icon here — only ensureBreathing(), which lets the running
    // (or freshly started) cycle perform the swap at its trough. This is what
    // defers the colour change to the trough for EVERY transition ordering:
    // off->pending->on, direct off->on, or a change landing mid-fade.
    //
    // CRITICAL: defer via Qt.callLater. ensureBreathing() reads the derived
    // bindings (targetPending / targetGlow / targetSource), but inside THIS
    // handler — powerState's own change slot — those sibling bindings have not
    // been re-evaluated yet and still hold the PREVIOUS state's values. Calling
    // ensureBreathing() synchronously here would decide against stale data: the
    // breath never starts on the pending click and the glow sticks on the wrong
    // colour (e.g. stays green after HVAC returns to off). callLater runs it once
    // at the end of this event-loop turn, after the bindings have settled (and
    // coalesces bursts of powerState changes into a single, current evaluation).
    onPowerStateChanged: Qt.callLater(ensureBreathing)

    GlowIcon {
        anchors.centerIn: parent
        iconSize: starter.iconSize
        glowRadiusPx: 32
        source: render.source
        glow: render.glow
        glowStrength: render.breath
    }

    // --- The breath ----------------------------------------------------------
    // ONE run of this animation = exactly one breath: fade the glow out to the
    // trough, hold hidden, commit the pending target colour + icon while hidden,
    // then fade back in with the (possibly new) colour. It does NOT loop itself;
    // onFinished re-arms it for the next breath only while there is still work
    // to do (see the restart rule). That makes the loop fully imperative and
    // keeps every colour/icon swap pinned to the trough.
    SequentialAnimation {
        id: breathCycle

        // Fade glow OUT to the trough (fully hidden).
        NumberAnimation {
            target: render
            property: "breath"
            to: 0.0
            duration: 1000
            easing.type: Easing.InOutSine
        }

        // "Hidden for a bit" — the deferred swap happens entirely inside this
        // invisible window so no colour change is ever seen mid-fade.
        PauseAnimation { duration: 140 }

        // Commit the target into the rendered state AT THE TROUGH. Whatever the
        // latest powerState resolved to is what fades back in. Because breath is
        // 0 here, swapping render.glow / render.source is imperceptible.
        ScriptAction { script: starter.commitTarget() }

        // Fade glow back IN with the freshly committed colour.
        NumberAnimation {
            target: render
            property: "breath"
            to: starter.fullStrength
            duration: 1000
            easing.type: Easing.InOutSine
        }

        // After a full breath, decide whether to breathe again.
        onFinished: starter.onBreathFinished()
    }

    // Copy the current target (colour + icon) into the rendered state. Called
    // only from the trough ScriptAction, so the visible swap is hidden.
    function commitTarget() {
        render.glow = starter.targetGlow
        render.source = starter.targetSource
        render.initialised = true
    }

    // Is the rendered glow already showing the target? Compares both colour and
    // disc, so it stays correct even if a future theme gave two states the same
    // glow colour (url == is the right comparison for QML urls).
    function renderMatchesTarget() {
        return render.initialised
            && Qt.colorEqual(render.glow, starter.targetGlow)
            && render.source == starter.targetSource
    }

    // Re-arm rule, evaluated after every completed breath. Breathe again IFF the
    // state is still pending OR the rendered colour has not yet caught up to the
    // target. Consequences:
    //   * Pending: always true -> the glow breathes continuously.
    //   * A resolution (on/off): the trough in THIS breath already committed the
    //     resolved colour, so renderMatchesTarget() is now true and pending is
    //     false -> we stop. breath has just faded back up to fullStrength, so the
    //     glow settles STEADY at full strength in the new colour. Exactly one
    //     catch-up breath runs after a resolution, then it rests.
    //   * A change that arrived after the trough (committed the OLD target):
    //     renderMatchesTarget() is false -> one more breath catches it up.
    function onBreathFinished() {
        if (starter.isCurrent && (starter.targetPending || !starter.renderMatchesTarget())) {
            breathCycle.restart()
        }
        // else: settle steady — breath is already at fullStrength, render holds
        // the resolved colour/icon, and the animation stays stopped.
    }

    // Start (or keep) breathing whenever there is outstanding work and the cycle
    // is not already running. Idempotent: calling it while running is a no-op,
    // so rapid re-clicks and bursts of powerState changes never stack animations
    // or restart mid-fade — the in-flight breath simply rides to its trough and
    // picks up the latest target there.
    function ensureBreathing() {
        if (!render.ready || !starter.isCurrent || breathCycle.running)
            return
        if (starter.targetPending || !starter.renderMatchesTarget())
            breathCycle.restart()
    }

    MouseArea {
        anchors.fill: parent
        onClicked: starter.clicked()
    }
}
