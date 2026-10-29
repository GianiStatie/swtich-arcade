/* Arcade gamepad shim.
 *
 * The two DragonRise panel encoders report their buttons in a non-standard
 * evdev order (physical A is the *last* raw button), and Chromium assigns
 * Gamepad API indices by raw code order — so games see wrong buttons (the
 * classic symptom: panel A = index 11 = R3).  webgame-server.py injects this
 * shim into every served page; it wraps navigator.getGamepads (and the
 * gamepadconnected event) and remaps the panels' buttons to the standard
 * layout, so games can use standard indices.
 *
 * Raw button -> physical label (from the ES input capture, 2026-10-16):
 *   0=customR 1=customL 2=Select 3=Start 4=LT 5=RT 6=LB 7=RB 8=Y 9=X 10=B 11=A
 * Standard indices: 0=A 1=B 2=X 3=Y 4=LB 5=RB 6=LT 7=RT 8=Select 9=Start
 *                   10=L3 11=R3
 * (the joystick already arrives on axes[0..1] = left stick X/Y, untouched)
 *
 * The built-in Combined Joy-Cons are hidden from the page. The keyboard
 * bridge owns them; leaving them visible makes Unity's Input System log
 * "Could not create a device for 'Nintendo Switch Combined Joy-Cons'" and
 * opens the native development console. Hiding the unused pad is not a
 * Joy-Con support path: the bridge and EmulationStation still see it.
 */
(function () {
    'use strict';
    // RAW_TO_STD[standardIndex] = raw index on the panel.
    var RAW_TO_STD = [11, 10, 9, 8, 6, 7, 4, 5, 2, 3, 1, 0];

    // webgame-server.py adds data-wiring="standard" on cabinets whose panels
    // already use the standard order; anything else keeps the remap.
    var scriptTag = document.currentScript;
    var PANEL_WIRING = scriptTag &&
        scriptTag.getAttribute('data-wiring') === 'standard'
        ? 'standard' : 'scrambled';

    function isPanel(pad) {
        return PANEL_WIRING === 'scrambled' &&
            !!pad && /DragonRise/.test(pad.id || '');
    }

    function isJoyCon(pad) {
        return !!pad && /Combined Joy-Cons/i.test(pad.id || '');
    }

    function remap(pad) {
        var proxy = {
            id: pad.id,
            index: pad.index,
            connected: pad.connected,
            timestamp: pad.timestamp,
            mapping: 'standard',
            axes: pad.axes,
            buttons: []
        };
        for (var i = 0; i < RAW_TO_STD.length; i++) {
            var b = pad.buttons[RAW_TO_STD[i]] ||
                    {pressed: false, touched: false, value: 0};
            proxy.buttons.push({pressed: b.pressed, touched: b.touched,
                                value: b.value});
        }
        return proxy;
    }

    var original = navigator.getGamepads
        ? navigator.getGamepads.bind(navigator) : null;
    if (original) {
        navigator.getGamepads = function () {
            var pads = original();
            var out = [];
            for (var i = 0; i < pads.length; i++) {
                var p = pads[i];
                out.push(isJoyCon(p) ? null
                         : p && isPanel(p) ? remap(p) : p);
            }
            out.item = function (i) { return this[i]; };
            return out;
        };
    }

    // Engines that store the object from the connected event need the
    // remapped pad there too. Registered before any page script (shim is in
    // <head>), so stopImmediatePropagation hides the raw event.
    var syntheticConnectedEvents = new WeakSet();
    window.addEventListener('gamepadconnected', function (ev) {
        if (isJoyCon(ev.gamepad)) {
            ev.stopImmediatePropagation();
            return;
        }
        if (syntheticConnectedEvents.has(ev) || !isPanel(ev.gamepad)) {
            return;
        }
        ev.stopImmediatePropagation();
        var e = new Event('gamepadconnected');
        e.gamepad = remap(ev.gamepad);
        syntheticConnectedEvents.add(e);
        window.dispatchEvent(e);
    }, true);
})();
