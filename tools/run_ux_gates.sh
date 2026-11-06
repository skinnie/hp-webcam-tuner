#!/bin/sh
# Run the ux-ui-agent-skills gates on ui/harness.html (regenerate it with tools/make_harness.py).
# Usage: KIT=/path/to/ux-ui-agent-skills sh tools/run_ux_gates.sh
# The kit launches Google Chrome (channel "chrome"); without it, replace { channel: 'chrome' } with {} in its scripts.
K=${KIT:?set KIT to a ux-ui-agent-skills checkout with npm deps}; H=$(cd $(dirname $0)/.. && pwd)/ui/harness.html; U=$(dirname $H); cd $K; export DS_REQUIRE_BROWSER=1; P=0; N=0
run(){ name="$1"; shift; out=$("$@" 2>&1); rc=$?; N=$((N+1)); [ $rc = 0 ] && P=$((P+1)); echo "[$([ $rc = 0 ] && echo PASS || echo FAIL)] $name"; [ $rc != 0 ] && echo "$out" | grep -vE "^\s*$" | tail -14 | sed 's/^/      /'; }
run "render WCAG light" node scripts/measure_render.mjs $H
run "render WCAG dark" node scripts/measure_render.mjs --dark $H
run "states light" node scripts/verify_states.mjs $H
run "states dark" node scripts/verify_states.mjs --dark $H
run "axe" node scripts/axe_audit.mjs $H
run "keyboard" node scripts/verify_keyboard.mjs $H
run "target size" node scripts/verify_target_size.mjs $H
run "reduced motion" node scripts/verify_reduced_motion.mjs $H
run "responsive 280-951" node scripts/verify_responsive.mjs $H
run "responsive scale 1.25" node scripts/verify_responsive.mjs $H --scale=1.25
run "mobile first" node scripts/verify_mobile_first.mjs $H
run "overflow" node scripts/verify_overflow.mjs $H
run "spacing" node scripts/verify_spacing.mjs $H
run "interactive" node scripts/verify_interactive.mjs $H
run "intent" node scripts/lint_intent.mjs $H
run "screen economy light" node scripts/verify_screen_economy.mjs $H
run "screen economy dark" node scripts/verify_screen_economy.mjs $H --dark
run "slop tells (strict)" node scripts/slop_tells.mjs --strict $H
run "hardcodes" python3 scripts/lint_hardcodes.py $U
run "theme refs" python3 scripts/validate_theme_refs.py --theme $U/tokens.css $U
run "native select / one-sided border" python3 scripts/lint_native_select.py $U
run "RTL" node scripts/verify_rtl.mjs $H
echo "RESULT $P/$N"
