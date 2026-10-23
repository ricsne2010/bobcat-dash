import os
"""Lights wiring diagram: key-controlled relay, fuses, switches, LED lamps, sense wires to the dash board."""
import schemdraw
import schemdraw.elements as elm
from PIL import Image

NET = "#1d4ed8"
NOTE = "#444444"
HV = "#b91c1c"       # heavy 12 V lighting current
SIG = "#1d4ed8"      # small signal / sense wires
d = schemdraw.Drawing(show=False)
d.config(fontsize=11, unit=2.5)


def label(p, text, size=10, color="black", halign="left", valign="center"):
    d.add(elm.Label().at(p).label(text, fontsize=size, color=color, halign=halign, valign=valign))


def lamp_to_ground(top, name):
    d.add(elm.Lamp(color=HV).down().at(top).length(2.6).label(name, loc="bottom", fontsize=9.5))
    d.add(elm.GroundChassis())


# ------------------------------------------------------------------ title
label((0, 4.2), "BOBCAT LIGHTS: KEY-CONTROLLED RELAY WIRING", 20)
label((0, 3.2), "The lights only get power while the key is ON. The switches pick which lights.  "
               "Red = lighting current (heavy wire).  Blue = sense wires to the dash board (thin wire, a few mA).",
      10.5, NOTE)

# ------------------------------------------------------------------ battery + main fuse -> relay 30
d.add(elm.Battery(color=HV).up().at((0, -7)).length(3))
label((0.5, -5.5), "12 V\nBATTERY", 10)
d.add(elm.Line(color=HV).up().length(3.5))                       # (0, -0.5)
d.add(elm.Line(color=HV).right().length(1))
d.add(elm.Fuse(color=HV).right().length(3.2).label("MAIN LIGHTS\nFUSE 15 A", loc="top", fontsize=9.5)
      .label("within 18 in\nof the battery", loc="bottom", fontsize=8.5, color=NOTE))
f1_end = d.here
d.add(elm.GroundChassis().at((0, -7)))

# relay as a box with its four numbered pins
relay = d.add(elm.Ic(
    pins=[elm.IcPin("30", side="left", anchorname="p30"), elm.IcPin("86", side="left", anchorname="p86"),
          elm.IcPin("87", side="right", anchorname="p87"), elm.IcPin("85", side="right", anchorname="p85")],
    size=(4.2, 3.6), pinspacing=2.2, edgepadW=0.6,
    label="LIGHTS RELAY\n12 V coil\n30 / 40 A", lblsize=10).anchor("p30").at((f1_end[0] + 1.6, f1_end[1])))
d.add(elm.Line(color=HV).at(f1_end).to(relay.p30))
label((relay.p30[0] - 0.2, relay.p30[1] + 0.35), "", 8)

# key switch -> 3 A fuse -> relay 86 (coil +)
key_pt = (0.9, relay.p86[1])
d.add(elm.Dot(open=True).at(key_pt))
label((key_pt[0] - 0.25, key_pt[1] + 0.75), "KEY SWITCH\nON / RUN terminal", 9.5, halign="left")
label((key_pt[0] - 0.25, key_pt[1] - 0.95), "(not ACC: ACC drops\nout while cranking)", 8.5, NOTE)
d.add(elm.Line(color=SIG).at(key_pt).right().length(0.8))
d.add(elm.Fuse(color=SIG).right().length(2.4).label("3 A", loc="top", fontsize=9))
d.add(elm.Line(color=SIG).to(relay.p86))
label((relay.p86[0] - 0.15, relay.p86[1] - 0.5), "coil +", 8, NOTE, halign="right")

# relay 85 -> ground (coil -)
d.add(elm.Line(color=SIG).at(relay.p85).right().length(1.2))
d.add(elm.GroundChassis())
label((relay.p85[0] + 0.15, relay.p85[1] - 0.5), "coil −", 8, NOTE)

# ------------------------------------------------------------------ relay 87 -> bus -> two fused branches
bus_x = relay.p87[0] + 2.6
d.add(elm.Line(color=HV).at(relay.p87).to((bus_x, relay.p87[1])))
y_front, y_back = relay.p87[1], relay.p87[1] - 8.5
d.add(elm.Dot(color=HV).at((bus_x, y_front)))
d.add(elm.Line(color=HV).at((bus_x, y_front)).to((bus_x, y_back)))
label((bus_x + 0.3, (y_front + y_back) / 2), "switched\n+12 V\n(only with\nkey ON)", 8.5, NOTE)

# FRONT branch: fuse -> SPST switch -> node -> 2 lamps; sense tap
d.add(elm.Fuse(color=HV).at((bus_x, y_front)).right().length(3).label("FRONT\n10 A", loc="top", fontsize=9.5))
d.add(elm.Line(color=HV).right().length(0.6))
d.add(elm.Switch(color=HV).right().length(2.6).label("FRONT LIGHT\nSWITCH\n(on / off)", loc="top", fontsize=9.5))
n_front = d.here
d.add(elm.Dot(color=HV).at(n_front))
d.add(elm.Line(color=HV).right().length(2.6))
d.add(elm.Dot(color=HV))
lamp_to_ground(d.here, "FRONT\nLED")
d.add(elm.Line(color=HV).at(d.elements[-3].end if False else (n_front[0] + 2.6, n_front[1])).right().length(2.6))
lamp_to_ground(d.here, "FRONT\nLED")
# sense tap FRONT
d.add(elm.Line(color=SIG).at(n_front).up().length(1.6))
d.add(elm.Fuse(color=SIG).right().length(2.2).label("1 A", loc="top", fontsize=9))
d.add(elm.Line(color=SIG).right().length(4.0))
d.add(elm.Dot(open=True).label("to dash board\nLIGHTS J11-1 FRONT", loc="right", fontsize=9.5, color=NET))

# REAR / WORK branch: fuse -> SPDT centre-off switch
d.add(elm.Fuse(color=HV).at((bus_x, y_back)).right().length(3).label("REAR / WORK\n7.5 A", loc="top", fontsize=9.5))
d.add(elm.Line(color=HV).right().length(0.6))
sw = d.add(elm.SwitchSpdt2(color=HV).right().anchor("a"))
label((bus_x + 0.3, sw.a[1] - 1.9), "3-POSITION SWITCH\nON-OFF-ON (SPDT)\nup = rear, middle = off,\ndown = work", 9, NOTE)
# REAR (upper throw)
y_rear = sw.b[1] + 1.4
d.add(elm.Line(color=HV).at(sw.b).to((sw.b[0] + 0.6, sw.b[1])))
d.add(elm.Line(color=HV).to((sw.b[0] + 0.6, y_rear)))
n_rear = (sw.b[0] + 1.6, y_rear)
d.add(elm.Line(color=HV).to(n_rear))
d.add(elm.Dot(color=HV).at(n_rear))
d.add(elm.Line(color=HV).at(n_rear).right().length(2.6))
d.add(elm.Dot(color=HV))
lamp_to_ground(d.here, "REAR\nLED")
d.add(elm.Line(color=HV).at((n_rear[0] + 2.6, y_rear)).right().length(2.6))
lamp_to_ground(d.here, "REAR\nLED")
# WORK (lower throw)
y_work = sw.c[1] - 4.2
d.add(elm.Line(color=HV).at(sw.c).to((sw.c[0] + 0.6, sw.c[1])))
d.add(elm.Line(color=HV).to((sw.c[0] + 0.6, y_work)))
n_work = (sw.c[0] + 1.6, y_work)
d.add(elm.Line(color=HV).to(n_work))
d.add(elm.Dot(color=HV).at(n_work))
d.add(elm.Line(color=HV).at(n_work).right().length(2.6))
lamp_to_ground(d.here, "WORK\nLIGHT")
# sense taps REAR (from the rear node, up) and WORK (from the switch's lower output, clear of the lamp)
work_tap = (sw.c[0] + 0.6, y_work + 1.7)
d.add(elm.Dot(color=HV).at(work_tap))
for node, pin, name, rise in [(n_rear, "J11-2", "REAR", 1.4), (work_tap, "J11-3", "WORK", 0.0)]:
    start = (node[0], node[1] + rise)
    if rise:
        d.add(elm.Line(color=SIG).at(node).to(start))
    d.add(elm.Line(color=SIG).at(start).to((n_rear[0] + 6.8, start[1])))
    d.add(elm.Fuse(color=SIG).right().length(2.2).label("1 A", loc="top", fontsize=9))
    d.add(elm.Line(color=SIG).right().length(0.6))
    d.add(elm.Dot(open=True).label(f"to dash board\nLIGHTS {pin} {name}", loc="right", fontsize=9.5, color=NET))

# ------------------------------------------------------------------ notes
nx, ny = -0.2, y_work - 4.6
label((nx, ny), "PARTS AND SIZES", 14)
notes = (
    "RELAY   12 V automotive \"mini ISO\" relay, 4-pin, normally open (pins 30, 85, 86, 87), 30 A or 40 A contacts,\n"
    "        in a weatherproof socket or pigtail. Get one with a built-in suppression diode or resistor (protects the key\n"
    "        switch contacts and the dash electronics from the coil's turn-off spike). With a DIODE type, polarity matters:\n"
    "        86 = + (from the key), 85 = ground. Go by the numbers printed on the relay and socket, not the pin positions.\n"
    "\n"
    "FUSES   Blade (ATO/ATC). Size each for its lights: fuse = total watts ÷ 12 × 1.25, rounded up. Example below.\n"
    "        Main lights fuse at the battery: 15 A.  FRONT (2 × 36 W = 6 A): 10 A.  REAR / WORK (work 40 W = 3.3 A): 7.5 A.\n"
    "        3 A on the relay coil wire.  1 A on each sense wire, right where it taps in.\n"
    "\n"
    "WIRE    14 AWG battery → main fuse → relay 30, and relay 87 → fuses.  16 AWG fuse → switch → lights.\n"
    "        18 AWG relay coil (86, 85).  20 AWG sense wires to the dash board.  Same-size wire for each light's ground.\n"
    "\n"
    "SWITCHES  Rated at least 15 A at 12 V DC: they carry the light current. Front: SPST on/off. Back: SPDT ON-OFF-ON.\n"
    "\n"
    "GROUNDS  Run each light's ground wire back to one solid ground point (the battery ground strap's frame bolt),\n"
    "         not to whatever bolt is nearest: paint and rust on a 1978 frame make poor grounds.\n"
    "\n"
    "EASIEST BUILD  A sealed fuse + relay box (\"weatherproof fuse and relay panel\", 6 fuses + 1 relay slot) holds the\n"
    "         relay and the FRONT and REAR/WORK fuses in one box with screw or ring terminals. The main 15 A fuse still goes\n"
    "         at the battery. Don't put the lights on the dash breakout board: they must keep working if the dash fails."
)
d.add(elm.Label().at((nx, ny - 0.8)).label(notes, fontsize=10, halign="left", valign="top", font="DejaVu Sans Mono"))

d.save("lights_wiring.png", dpi=150, transparent=False)
img = Image.open("lights_wiring.png").convert("RGB")
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lights-wiring.jpg"), quality=92)
print(img.size)
