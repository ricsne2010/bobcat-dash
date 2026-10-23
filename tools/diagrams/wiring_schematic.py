import os
import schemdraw
import schemdraw.elements as elm
from PIL import Image

NET = "#1d4ed8"     # net label colour
NOTE = "#555555"
HV = "#b91c1c"      # 12 V side
d = schemdraw.Drawing(show=False)
d.config(fontsize=11, unit=2.5)


def net(p, name, loc="right"):
    d.add(elm.Dot(open=True).at(p).label(name, loc=loc, color=NET, fontsize=10.5))


def title(p, text, sub=None):
    d.add(elm.Label().at(p).label(text, fontsize=14, halign="left", color="black"))
    if sub:
        d.add(elm.Label().at((p[0], p[1] - 0.7)).label(sub, fontsize=9.5, halign="left", color=NOTE))


def plus12(p):
    d.add(elm.Vdd(color=HV).at(p).label("+12V IGN", fontsize=9.5, color=HV))


def clamp(node, x_off, gnd_y_len=2.5):
    """Schottky clamps (to 3.3 V and to GND) + 0.1 uF from an ADC input node."""
    a = (node[0] + x_off, node[1])
    d.add(elm.Line().at(node).to(a))
    d.add(elm.Dot().at(a))
    d.add(elm.Schottky().up().at(a).length(1.8).label("BAT85", loc="bottom", fontsize=9))
    d.add(elm.Vdd().label("3.3V", fontsize=9, color=NET))
    d.add(elm.Schottky().down().reverse().at(a).length(gnd_y_len).label("BAT85", loc="bottom", fontsize=9))
    d.add(elm.Ground())
    b = (a[0] + 2.2, a[1])
    d.add(elm.Line().at(a).to(b))
    d.add(elm.Capacitor().down().at(b).length(gnd_y_len).label("0.1µF", loc="bottom", fontsize=9))
    d.add(elm.Ground())
    return b


# ------------------------------------------------------------------ title
d.add(elm.Label().at((0, 3)).label("BOBCAT DIGITAL DASH — WIRING SCHEMATIC", fontsize=20, halign="left"))
d.add(elm.Label().at((0, 2)).label(
    "Raspberry Pi 4/5  ·  ADS1115 ADC  ·  PC817 optocouplers.   Blue labels with the same name are connected.   "
    "Red = 12 V vehicle side.", fontsize=10.5, halign="left", color=NOTE))

# ------------------------------------------------------------------ 1. power
title((0, 0), "1. POWER")
plus12((1, -2.5))
d.add(elm.Line().at((1, -2.5)).right(0.8))
d.add(elm.Fuse(color=HV).right().label("3A fuse", fontsize=9.5))
d.add(elm.Line().right(0.8))
buck = d.add(elm.Ic(
    pins=[elm.IcPin("IN−", side="left", anchorname="inn"), elm.IcPin("IN+", side="left", anchorname="inp"),
          elm.IcPin("OUT−", side="right", anchorname="outn"), elm.IcPin("OUT+", side="right", anchorname="outp")],
    size=(5, 3), pinspacing=1.4, label="12V → 5V BUCK\n5A, 8–36V in", lblsize=10).theta(0).anchor("inp").at(d.here))
d.add(elm.Line().at(buck.inn).left(0.8))
d.add(elm.GroundChassis())
d.add(elm.Line().at(buck.outp).right(1.2))
net(d.here, "+5V")
d.add(elm.Line().at(buck.outn).right(1.2))
d.add(elm.Ground())
d.add(elm.Label().at((0.2, -7.2)).label(
    "Hand-wired: feed from the ignition switch (the Pi\nloses power at key-off). Chassis ground and Pi GND\nmeet at the buck converter.\n"
    "Breakout board rev 2.0: constant battery feed\n(7.5A fuse at the battery) + a separate IGN wire.\nThe board keeps the Pi on after key-off so it can\nsave and shut down. See breakout-board/README.md.",
    fontsize=9, halign="left", color=NOTE))

# ------------------------------------------------------------------ 2. Pi + ADS1115
title((15, 0), "2. RASPBERRY PI + ADS1115")
pi = d.add(elm.Ic(
    pins=[elm.IcPin("GPIO21 (pin 40)", side="left", anchorname="g21"),
          elm.IcPin("GPIO19 (pin 35)", side="left", anchorname="g19"),
          elm.IcPin("GPIO18 (pin 12)", side="left", anchorname="g18"),
          elm.IcPin("GPIO5 (pin 29)", side="left", anchorname="g5"),
          elm.IcPin("GPIO27 (pin 13)", side="left", anchorname="g27"),
          elm.IcPin("GPIO24 (pin 18)", side="left", anchorname="g24"),
          elm.IcPin("GPIO23 (pin 16)", side="left", anchorname="g23"),
          elm.IcPin("GPIO22 (pin 15)", side="left", anchorname="g22"),
          elm.IcPin("GPIO17 (pin 11)", side="left", anchorname="g17"),
          elm.IcPin("GND (pin 9)", side="left", anchorname="gndl"),
          elm.IcPin("5V (pin 2)", side="left", anchorname="v5"),
          elm.IcPin("GND (pin 6)", side="right", anchorname="gndr"),
          elm.IcPin("GPIO3 SCL (pin 5)", side="right", anchorname="scl"),
          elm.IcPin("GPIO2 SDA (pin 3)", side="right", anchorname="sda"),
          elm.IcPin("3V3 (pin 1)", side="right", anchorname="v33")],
    size=(10, 11.6), pinspacing=1.0, label="RASPBERRY PI\n(40-pin header)", lblofst=0).theta(0).at((19, -14.2)))
for anchor, name in [("v5", "+5V"), ("g17", "GPIO17"), ("g22", "GPIO22"), ("g23", "GPIO23"), ("g24", "GPIO24"),
                     ("g27", "GPIO27"), ("g5", "GPIO5"), ("g18", "GPIO18"), ("g19", "GPIO19"), ("g21", "GPIO21")]:
    d.add(elm.Line().at(getattr(pi, anchor)).left(1.5))
    net(d.here, name, loc="left")
d.add(elm.Line().at(pi.gndl).left(1.5))
d.add(elm.Ground())

ads = d.add(elm.Ic(
    pins=[elm.IcPin("GND", side="left", anchorname="gnd"), elm.IcPin("SCL", side="left", anchorname="scl"),
          elm.IcPin("SDA", side="left", anchorname="sda"), elm.IcPin("VDD", side="left", anchorname="vdd"),
          elm.IcPin("A3", side="right", anchorname="a3"), elm.IcPin("A2", side="right", anchorname="a2"),
          elm.IcPin("A1", side="right", anchorname="a1"), elm.IcPin("A0", side="right", anchorname="a0"),
          elm.IcPin("ADDR", side="bottom", anchorname="addr")],
    size=(3.6, 4.4), pinspacing=1.0, label="ADS1115\n16-bit ADC\naddr 0x48", lblsize=10).theta(0).anchor("vdd").at((pi.v33[0] + 4, pi.v33[1])))
for a in ("vdd", "sda", "scl", "gnd"):
    d.add(elm.Line().at(getattr(pi, "v33" if a == "vdd" else ("gndr" if a == "gnd" else a))).to(getattr(ads, a)))
d.add(elm.Dot().at((pi.v33[0] + 1.2, pi.v33[1])))
d.add(elm.Line().up(1))
net(d.here, "3.3V", loc="top")
d.add(elm.Dot().at((pi.gndr[0] + 1.2, pi.gndr[1])))
d.add(elm.Line().down(3.2))
d.add(elm.Ground())
d.add(elm.Line().at(ads.addr).down(0.8))
d.add(elm.Ground())
for a, name in [("a0", "A0"), ("a1", "A1")]:
    d.add(elm.Line().at(getattr(ads, a)).right(1.5))
    net(d.here, name)
for a, name in [("a2", "A2"), ("a3", "A3")]:
    d.add(elm.Line().at(getattr(ads, a)).right(1.5))
    net(d.here, name)

# ------------------------------------------------------------------ 3. battery voltage
Y2 = -18
title((0, Y2), "3. BATTERY VOLTAGE → A0", "47k / 10k divider, ratio 5.7  (15.5 V reads 2.72 V)")
plus12((1, Y2 - 2.5))
d.add(elm.Resistor().down().at((1, Y2 - 2.5)).length(2.5).label("47kΩ", fontsize=10))
node = d.add(elm.Dot()).center
d.add(elm.Resistor().down().at(node).length(2.5).label("10kΩ", fontsize=10))
d.add(elm.Ground())
end = clamp(node, 2.2)
d.add(elm.Line().at(end).right(1.5))
net(d.here, "A0")

# ------------------------------------------------------------------ 4. fuel sender
title((12, Y2), "4. FUEL SENDER → A1", "Sender wired only to the dash (no original gauge)")
d.add(elm.Vdd().at((13, Y2 - 2.5)).label("3.3V", fontsize=9.5, color=NET))
d.add(elm.Resistor().down().at((13, Y2 - 2.5)).length(2.5).label("220Ω", fontsize=10))
node = d.add(elm.Dot()).center
d.add(elm.ResistorVar(color=HV).down().at(node).length(2.5).label("FUEL\nSENDER\n(in tank)", fontsize=9.5))
d.add(elm.GroundChassis())
end = clamp(node, 2.2)
d.add(elm.Line().at(end).right(1.5))
net(d.here, "A1")
d.add(elm.Label().at((12, Y2 - 9.6)).label(
    "Run dash.py --calibrate and enter the empty / half / full\n"
    "readings in config.toml.",
    fontsize=9, halign="left", color=NOTE))

# ------------------------------------------------------------------ 5. warning switches + tach
Y3 = -30.5
title((0, Y3), "5. WARNING SWITCHES + TACH",
      "Oil + tach: PC817 optocoupler. Switch closes → LED lights → GPIO low.   Filter + temp: monitored on the ADC with a 4.7k resistor AT THE SWITCH: "
      "1.65 V = OK, 0 V = switch closed, 3.3 V = wire broken.")


def opto_channel(x, name, gpio, sw_label, hall=False):
    top = (x + 3, Y3 - 3)
    plus12(top)
    r = d.add(elm.Resistor(color=HV).down().at(top).length(2).label("2.2kΩ", fontsize=9.5))
    op = d.add(elm.Optocoupler().theta(0).anchor("anode").at(r.end))
    d.add(elm.Label().at((op.collector[0] - 0.3, op.anode[1] + 0.55)).label("PC817", fontsize=9))
    a, c = op.anode, op.cathode
    # reverse protection diode
    d.add(elm.Line().at(a).left(1.7))
    d.add(elm.Diode().up().at((a[0] - 1.7, c[1])).toy(a[1]).label("1N4148", loc="top", fontsize=8, ofst=0.1))
    d.add(elm.Line().at(c).left(1.7))
    # Pi side
    if hall:
        d.add(elm.Line().at(op.collector).right(1.0))
        n = d.add(elm.Dot()).center
        d.add(elm.Resistor().up().at(n).length(2).label("4.7kΩ", loc="bottom", fontsize=9))
        d.add(elm.Vdd().label("3.3V", fontsize=9, color=NET))
        d.add(elm.Line().at(n).right(0.8))
    else:
        d.add(elm.Line().at(op.collector).right(1.8))
    net(d.here, gpio)
    d.add(elm.Line().at(op.emitter).right(0.8))
    d.add(elm.Ground())
    # vehicle side
    d.add(elm.Line(color=HV).at(c).down(1.2))
    if hall:
        h = d.add(elm.Ic(
            pins=[elm.IcPin("SIG", side="top", anchorname="sig"),
                  elm.IcPin("+", side="left", anchorname="vp"),
                  elm.IcPin("GND", side="bottom", anchorname="gnd")],
            size=(4.2, 2.6), label="HALL SENSOR\nNJK-5002C", lblsize=9).theta(0).anchor("sig").at(d.here))
        d.add(elm.Line(color=HV).at(h.vp).left(1.2))
        plus12(d.here)
        d.add(elm.Line().at(h.gnd).down(0.4))
        d.add(elm.GroundChassis())
        d.add(elm.Label().at((h.gnd[0] + 2.5, h.gnd[1] + 0.3)).label(
            "Hall sensor OPTION. Brown +12V, blue GND,\nblack SIG. Magnet on crank pulley:\npulses_per_rev = 1.\nTHIS MACHINE reads the ignition coil −\nterminal on the breakout board's COIL\ninput instead (pulses_per_rev = 2)",
            fontsize=9, halign="left", valign="top", color=NOTE))
    else:
        d.add(elm.Switch(color=HV).down().length(2.2).label(sw_label, loc="bottom", fontsize=9.5))
        d.add(elm.GroundChassis())
    d.add(elm.Label().at((x, Y3 - 2)).label(name, fontsize=12, halign="left", color="black"))


def monitored_channel(x, name, adc, sw_label, pin):
    """Switch with a 4.7k end-of-line resistor at the switch, read on an ADC input."""
    d.add(elm.Label().at((x, Y3 - 2)).label(name, fontsize=12, halign="left", color="black"))
    top = (x + 1.5, Y3 - 3)
    d.add(elm.Vdd().at(top).label("3.3V", fontsize=9, color=NET))
    d.add(elm.Resistor().down().at(top).length(2.2).label("4.7kΩ\npull-up", loc="bottom", fontsize=9))
    n = d.add(elm.Dot()).center
    d.add(elm.Resistor().right().at(n).length(2.4).label("10kΩ", fontsize=9))
    m = d.add(elm.Dot()).center
    end = clamp(m, 0.9, gnd_y_len=2.2)
    d.add(elm.Line().at(end).right(1.0))
    net(d.here, adc)
    # harness wire down to the switch
    d.add(elm.Line().at(n).down(1.6))
    d.add(elm.Dot(open=True).label(f"J4 {pin}", loc="left", fontsize=9, color=NOTE))
    hw = d.add(elm.Line(color=HV, ls="--").down(3.0))
    d.add(elm.Label().at((hw.center[0] - 0.25, hw.center[1])).label("harness\nwire", halign="right", fontsize=8.5, color=HV))
    s_node = d.add(elm.Dot(color=HV)).center
    sw = d.add(elm.Switch(color=HV).down().length(2.2).label(sw_label, loc="bottom", fontsize=9))
    g1 = d.add(elm.GroundChassis())
    ln = d.add(elm.Line(color=HV).at(s_node).right(2.6))
    eol = d.add(elm.Resistor(color=HV).down().length(2.2).label("4.7kΩ\nEOL", loc="bottom", fontsize=9, color=HV))
    g2 = d.add(elm.GroundChassis())
    d.add(elm.EncircleBox([sw, ln, eol, g1, g2], padx=0.5, pady=0.3).linestyle("--").color(HV)
          .label("AT THE SWITCH", loc="bottom", fontsize=9.5, color=HV))


opto_channel(0.5, "ENGINE OIL PRESSURE", "GPIO22", "OIL PRESS.\nSWITCH\n(closes when\npressure low)")
opto_channel(12, "TACHOMETER", "GPIO17", None, hall=True)
monitored_channel(25, "HYD FILTER BYPASS", "A2", "FILTER\nBYPASS SW", "FILT")
monitored_channel(38, "HYD OIL TEMP", "A3", "TEMP SW\n(hot)", "TEMP")
d.add(elm.Label().at((25, Y3 - 15.6)).label(
    "Filter + temp: nothing else connects to these switches (any 12 V on the wire reads as broken).\n"
    "Optional status LEDs: GPIO23 / GPIO24 → 470Ω → LED → GND (on = active, blinking = wire broken).",
    fontsize=9, halign="left", color=NOTE))


# ------------------------------------------------------------------ 6. alarm horn, silence button, speaker
Y4 = Y3 - 18
title((0, Y4), "6. ALARM HORN, SILENCE BUTTON + SPEAKER",
      "Horn pulses on red alarms. The button silences current alarms. The speaker plays the start-up chime and in-cab alert tones.")

# horn driver: +12V -> fuse -> piezo -> MOSFET (low-side) -> chassis
d.add(elm.Label().at((0.5, Y4 - 2)).label("HORN DRIVER", fontsize=12, halign="left", color="black"))
plus12((5, Y4 - 3))
d.add(elm.Fuse(color=HV).down().at((5, Y4 - 3)).length(2).label("1A fuse", fontsize=9.5))
pz = d.add(elm.Ic(
    pins=[elm.IcPin("−", side="bottom", anchorname="neg"), elm.IcPin("+", side="top", anchorname="pos")],
    size=(3.6, 1.8), label="PIEZO ALARM\n12V · 100–110 dB", lblsize=9.5, color=HV).theta(0).anchor("pos").at(d.here))
d.add(elm.Line(color=HV).at(pz.neg).down(0.8))
fet = d.add(elm.NFet().theta(0).anchor("drain").at(d.here))
d.add(elm.Label().at((fet.drain[0] - 0.5, fet.gate[1])).label("N-MOSFET\nAO3400 /\nIRLZ44N", fontsize=9, halign="right"))
d.add(elm.GroundChassis().at(fet.source))
d.add(elm.Line().at(fet.gate).right(0.8))
g = d.add(elm.Dot()).center
d.add(elm.Resistor().right().at(g).length(2.2).label("100Ω", fontsize=9.5))
d.add(elm.Line().right(0.5))
net(d.here, "GPIO27")
d.add(elm.Resistor().down().at(g).length(2.2).label("10kΩ\npull-down", loc="bottom", fontsize=9))
d.add(elm.Ground())
# optional flyback diode across the alarm (coil horn / relay only)
top_node = (5, pz.pos[1] + 0.4)
d.add(elm.Dot(color=HV).at(top_node))
d.add(elm.Line(color=HV, ls="--").at(top_node).left(3.2))
d.add(elm.Diode(color=HV, ls="--").up().at((top_node[0] - 3.2, pz.neg[1] - 0.4)).toy(top_node[1])
      .label("1N4007\n(coil horn\nonly)", loc="top", fontsize=8.5))
d.add(elm.Line(color=HV, ls="--").at((top_node[0] - 3.2, pz.neg[1] - 0.4)).right(3.2))
d.add(elm.Dot(color=HV).at((5, pz.neg[1] - 0.4)))
d.add(elm.Label().at((0.5, Y4 - 12.6)).label(
    "The 10k keeps the horn off while the Pi boots.\nOr use a 1-channel opto relay module on GPIO27\n(set active_high = false if it triggers on LOW).",
    fontsize=9, halign="left", color=NOTE))

# silence button
d.add(elm.Label().at((15.5, Y4 - 2)).label("SILENCE BUTTON", fontsize=12, halign="left", color="black"))
net((17, Y4 - 3.6), "GPIO5")
d.add(elm.Line().at((17, Y4 - 3.6)).down(0.8))
d.add(elm.Button().down().length(2.4).label("momentary\npush button", loc="bottom", fontsize=9.5))
d.add(elm.Ground())
d.add(elm.Label().at((15.5, Y4 - 9.4)).label(
    "Internal pull-up is on.\nMount within reach\nof a gloved hand.", fontsize=9, halign="left", color=NOTE))

# speaker amplifier
d.add(elm.Label().at((24.5, Y4 - 2)).label("SPEAKER AMPLIFIER", fontsize=12, halign="left", color="black"))
amp = d.add(elm.Ic(
    pins=[elm.IcPin("DIN", side="left", anchorname="din"), elm.IcPin("LRC", side="left", anchorname="lrc"),
          elm.IcPin("BCLK", side="left", anchorname="bclk"), elm.IcPin("GND", side="left", anchorname="gnd"),
          elm.IcPin("Vin", side="left", anchorname="vin"),
          elm.IcPin("−", side="right", anchorname="neg"), elm.IcPin("+", side="right", anchorname="pos")],
    size=(4, 5.6), pinspacing=1.0, label="MAX98357A\nI2S amp\n3W", lblsize=10).theta(0).at((28.5, Y4 - 9.2)))
for a, name in [("vin", "+5V"), ("bclk", "GPIO18"), ("lrc", "GPIO19"), ("din", "GPIO21")]:
    d.add(elm.Line().at(getattr(amp, a)).left(1.5))
    net(d.here, name, loc="left")
d.add(elm.Line().at(amp.gnd).left(0.8))
d.add(elm.Ground())
d.add(elm.Line().at(amp.pos).right(1.2))
spk_top = d.here
d.add(elm.Line().at(amp.neg).right(1.2))
spk = d.add(elm.Speaker().theta(0).anchor("in1").at((spk_top[0] + 0.6, spk_top[1])).label("4Ω 3W\nspeaker", loc="right", fontsize=9.5))
d.add(elm.Line().at(spk_top).to(spk.in1))
d.add(elm.Wire("-|").at((spk_top[0], amp.neg[1])).to(spk.in2))
d.add(elm.Label().at((24.5, Y4 - 12.6)).label(
    "Add to /boot/firmware/config.txt:\n    dtoverlay=max98357a\nOr: USB sound card + powered speaker.",
    fontsize=9, halign="left", color=NOTE))

# ------------------------------------------------------------------ parts list
d.add(elm.Label().at((27, Y2)).label("PARTS", fontsize=14, halign="left"))
d.add(elm.Label().at((27, Y2 - 0.9)).label(
    "1   Raspberry Pi 4 or 5 + HDMI LCD\n"
    "1   ADS1115 16-bit ADC breakout (I2C)\n"
    "2   PC817 optocoupler\n"
    "1   12V→5V automotive buck converter, 5A\n"
    "1   3A inline fuse + holder\n"
    "1   NJK-5002C Hall sensor + magnet\n"
    "1   47kΩ     3  10kΩ     1  220Ω\n"
    "2   2.2kΩ    5  4.7kΩ  (2 fit AT the switches)\n"
    "8   BAT85 Schottky diode (ADC clamps)\n"
    "2   1N4148 diode\n"
    "4   0.1µF capacitor\n"

    "\n"
    "ALARM + SOUND\n"
    "1   12V piezo alarm, 100–110 dB, IP65+\n"
    "1   Logic-level N-MOSFET (AO3400 / IRLZ44N)\n"
    "1   100Ω     1  10kΩ     1  1A fuse\n"
    "1   Momentary push button (silence)\n"
    "1   MAX98357A I2S amplifier board\n"
    "1   4Ω 3W weather-resistant speaker\n"
    "1   1N4007 (only for a coil horn / relay)\n"
    "\n"
    "CHARGING (Delco 10SI)\n"
    "1   1N4001 diode     1  47Ω 5W resistor\n"
    "1   fusible link / 60 A breaker (BAT stud)",
    fontsize=10.5, halign="left", valign="top", font="DejaVu Sans Mono"))

# ------------------------------------------------------------------ 7. charging: Delco 10SI
Y6 = Y4 - 16
title((0, Y6), "7. CHARGING: DELCO 10SI 3-WIRE ALTERNATOR (internal regulator)",
      "Replaces the old generator + external regulator. The dash reads the voltage at the board's POWER IN, so the "
      "regulator's sense wire (2) and the board both go to the battery +.")
yJ = Y6 - 5.5                                       # battery + junction row
# battery: + up to the junction, - to the ground point
bat = d.add(elm.Battery(color=HV).up().at((3, Y6 - 13.5)).length(3).label("12 V\nBATTERY", loc="bottom", fontsize=9.5))
d.add(elm.Line(color=HV).at(bat.end).toy(yJ))
d.add(elm.Dot(color=HV).at((3, yJ)))
d.add(elm.Label().at((0.4, yJ + 0.5)).label("BATTERY +\n(or starter\nterminal)", fontsize=8.5, halign="left", color=NOTE))
d.add(elm.Line().at(bat.start).down(0.6))
gp = d.add(elm.GroundChassis())
d.add(elm.Label().at((3.6, Y6 - 14.6)).label("main ground point:\nbattery − strap to frame", fontsize=8.5, halign="left", color=NOTE))
# alternator
alt = d.add(elm.Ic(
    pins=[elm.IcPin("BAT", side="left", anchorname="bat"), elm.IcPin("2", side="top", anchorname="s2"),
          elm.IcPin("1", side="right", anchorname="t1"), elm.IcPin("case", side="bottom", anchorname="case")],
    size=(5, 3.4), label="DELCO 10SI\nalternator", lblsize=10.5, color=HV).theta(0).anchor("bat").at((14, yJ)))
# BAT stud: heavy wire + fusible link to the junction
d.add(elm.Line(color=HV).at((3, yJ)).right(1.5))
d.add(elm.Fuse(color=HV).right().length(4).label("fusible link /\n60 A breaker", loc="top", fontsize=9)
      .label("8 AWG (10 AWG ≤ 45 A)", loc="bottom", fontsize=8.5, color=NOTE))
d.add(elm.Line(color=HV).to(alt.bat))
# terminal 2: sense, back to the battery +
top_y = alt.s2[1] + 1.4
d.add(elm.Line(color=HV).at(alt.s2).toy(top_y))
d.add(elm.Line(color=HV).tox(3))
d.add(elm.Line(color=HV).toy(yJ))
d.add(elm.Label().at((8.2, top_y + 0.45)).label("terminal 2 = voltage SENSE, 18 AWG to battery +", fontsize=9, color=HV))
# case ground
d.add(elm.Line().at(alt.case).down(0.8))
d.add(elm.GroundChassis())
d.add(elm.Label().at((alt.case[0] + 0.5, alt.case[1] - 1.9)).label("case → engine block →\nheavy strap to frame", fontsize=8.5, halign="left", color=NOTE))
# terminal 1: excite, from KEY ON/RUN through the diode and resistor
d.add(elm.Line(color=HV).at(alt.t1).right(0.6))
d.add(elm.Diode(color=HV).right().reverse().length(2.8)           # band (cathode) on the alternator side
      .label("1N4001", loc="top", fontsize=9.5).label("band → alternator", loc="bottom", fontsize=8.5, color=NOTE))
d.add(elm.Resistor(color=HV).right().length(3).label("47Ω 5W", loc="top", fontsize=9.5))
d.add(elm.Line(color=HV).right(0.6))
net(d.here, "KEY ON / RUN")
d.add(elm.Label().at((alt.t1[0] + 0.3, alt.t1[1] - 1.1)).label("terminal 1 = EXCITE", fontsize=9, halign="left", color=HV))
# breakout board power in
brd = d.add(elm.Ic(
    pins=[elm.IcPin("GND", side="left", anchorname="gnd"), elm.IcPin("BAT+", side="left", anchorname="batp"),
          elm.IcPin("IGN", side="right", anchorname="ign")],
    size=(5, 2.6), pinspacing=1.2, label="BREAKOUT BOARD\nJ2 POWER IN", lblsize=9.5).theta(0).anchor("batp").at((14, Y6 - 11.2)))
d.add(elm.Line(color=HV).at((3, Y6 - 9.6)).tox(5))
d.add(elm.Dot(color=HV).at((3, Y6 - 9.6)))
d.add(elm.Fuse(color=HV).right().length(3).label("7.5 A", loc="top", fontsize=9))
d.add(elm.Line(color=HV).toy(brd.batp[1]))
d.add(elm.Line(color=HV).to(brd.batp))
d.add(elm.Line().at(brd.gnd).left(1.6))
d.add(elm.GroundChassis())
d.add(elm.Line(color=HV).at(brd.ign).right(0.6))
d.add(elm.Fuse(color=HV).right().length(2.4).label("2 A", loc="top", fontsize=9))
d.add(elm.Line(color=HV).right(0.6))
net(d.here, "KEY ON / RUN")
d.add(elm.Label().at((3.3, Y6 - 8.9)).label("battery + (constant)", fontsize=8.5, halign="left", color=NOTE))
# notes
d.add(elm.Label().at((29, Y6 - 2.2)).label(
    "TERMINAL 1 (EXCITE)   No charge lamp: the dash shows NOT CHARGING instead.\n"
    "  1N4001: once running, the 10SI pushes ~14 V back out of terminal 1. Without the\n"
    "  diode that keeps the key's ON circuit live after key-off: the PerTronix keeps\n"
    "  sparking (engine won't stop) and the dash never sees key-off.\n"
    "  47 Ω 5 W: limits the current with the key on and the engine stopped to ~0.25 A,\n"
    "  what the charge lamp used to pass. With a diode alone, terminal 1 feeds the field\n"
    "  directly: ~3-4 A, more than a 1N4001's 1 A rating, and a flat battery if the key\n"
    "  is left on. If the alternator's instructions give a value, use theirs.\n"
    "\n"
    "TERMINAL 2 (SENSE)   To battery + (same point as the board's BAT+), so the regulator\n"
    "  holds the voltage that the dash measures.\n"
    "\n"
    "GROUNDS   Engine block to frame: a heavy strap, clean metal. Board GND to the main\n"
    "  ground point. A poor engine ground makes the alternator charge wrong.\n"
    "\n"
    "CHECK + CALIBRATE   Engine running, fast idle: meter at the battery, 13.9-14.6 V.\n"
    "  Set divider_ratio in config.toml so the dash agrees (see the comment there).\n"
    "  Then turn the key off: the engine must stop and the dash count down KEY OFF.",
    fontsize=9.5, halign="left", valign="top", font="DejaVu Sans Mono"))

# ------------------------------------------------------------------ legend
Y5 = Y6 - 17
d.add(elm.Ground().at((1, Y5)))
d.add(elm.Label().at((1.8, Y5 - 0.3)).label("Pi / signal ground", fontsize=9.5, halign="left"))
d.add(elm.GroundChassis().at((8, Y5)))
d.add(elm.Label().at((8.8, Y5 - 0.3)).label("Machine chassis ground", fontsize=9.5, halign="left"))
d.add(elm.Label().at((17, Y5 - 0.3)).label(
    "Never connect 12 V directly to a Pi pin. Pi GPIO and ADS1115 inputs are 3.3 V max.", fontsize=9.5, halign="left", color=HV))

d.save("schematic.png", dpi=170, transparent=False)
img = Image.open("schematic.png").convert("RGB")
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "wiring-schematic.jpg"), quality=92)
print(img.size)
