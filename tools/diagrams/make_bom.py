import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation

F = "Arial"
wb = Workbook(); ws = wb.active; ws.title = "BOM"

# (qty, part, spec, example part no., where used, notes)
SECTIONS = [
 ("COMPUTER + DISPLAY", [
  (1, "Raspberry Pi", "Pi 4 Model B (2 GB+) or Pi 5", "Raspberry Pi 4B / Pi 5", "Sch. 2", "Pi 5 needs a 5 A supply"),
  (1, "microSD card", "16–32 GB, high-endurance, A1/A2", "SanDisk High Endurance", "—", "Do NOT enable the overlay file system: it would erase the engine hours"),
  (1, "Pi 5 RTC battery", "Rechargeable lithium-manganese coin cell, 2-pin JST-SH lead (Pi 5 only)", "Raspberry Pi RTC battery (Panasonic ML-2020)", "README: Screens / Dates", "Plugs into the Pi 5's BAT socket; keeps the clock through key-off; setup-pi.sh turns its charging on. Never a CR2032 (not rechargeable). Rated to 60 °C"),
  (1, "Weatherproof HDMI monitor", "12 V powered, IP65+, ≥800 nits, 1024×768 or similar", "—", "README: Monitor", "Sunlight-readable strongly recommended. Note its native resolution for the splash + video= setting"),
  (1, "HDMI cable", "Micro-HDMI to HDMI, long enough to reach the monitor (≤5 m)", "—", "README: Monitor", "Pi 4/5 use micro-HDMI. Strain-relieve both ends"),
  (1, "Inline fuse holder + fuse", "Blade type, size from the monitor's manual (typ. 3–5 A)", "—", "README: Monitor", "Key-switched 12 V feed to the monitor. Ground the monitor at the board's ground point"),
  (1, "Heatsink or fan case", "For Pi 4/5", "—", "—", "Enclosed cab gets hot in summer"),
 ]),
 ("POWER", [
  (1, "Buck converter 12 V → 5 V", "5 A, 8–36 V input, automotive", "—", "Sch. 1", "Not a cigarette-lighter USB plug"),
  (1, "Inline fuse holder + fuse", "Blade type, 7.5 A", "—", "Sch. 1", "At the battery, on the constant +12 V feed to the board's BAT+ (rev 2.0). Hand-wired without the board: 3 A on the ignition feed instead"),
  (1, "Inline fuse holder + fuse", "Blade type, 2 A", "—", "Board README", "At the key switch, on the IGN sense wire to the board (rev 2.0)"),
  (1, "USB-C power lead / pigtail", "Buck output to Pi", "—", "Sch. 1", "Or feed the Pi's 5 V header pins"),
 ]),
 ("SENSOR INTERFACE", [
  (1, "ADC board", "ADS1115 16-bit, 4-ch, I2C", "Adafruit 1085 (STEMMA QT, two header rows)", "Sch. 2–4", "Plugs straight into the board (rev 2.8). Address 0x48 (ADDR to GND)"),
  (4, "M2.5 standoff + 8 screws", "11 mm female-female, round (or 5 mm hex)", "—", "Board README", "Screws the ADS1115 module down to the board (holes H5-H8) against vibration"),
  (2, "Optocoupler", "PC817", "PC817", "Sch. 5", "Oil pressure and tach"),
  (1, "Resistor 47 kΩ", "1/4 W, 1 %", "—", "Sch. 3", "Battery divider top (ratio 5.7)"),
  (4, "Resistor 10 kΩ", "1/4 W, 1 %", "—", "Sch. 3, 5, 6", "Battery divider, filter/temp series (2), horn gate pull-down"),
  (1, "Resistor 220 Ω", "1/4 W", "—", "Sch. 4", "Fuel sender pull-up"),
  (2, "Resistor 2.2 kΩ", "1/4 W", "—", "Sch. 5", "Optocoupler LED current"),
  (3, "Resistor 4.7 kΩ", "1/4 W, 1 %", "—", "Sch. 5", "Tach pull-up, filter/temp pull-ups to 3.3 V"),
  (8, "Schottky diode", "BAT85, DO-35", "BAT85", "Sch. 3, 4, 5", "ADC input clamps: one to 3.3 V, one to GND per input (A0-A3)"),
  (2, "Signal diode", "1N4148", "1N4148", "Sch. 5", "Reverse protection across opto LEDs"),
  (4, "Capacitor 0.1 µF", "Ceramic, 50 V", "—", "Sch. 3, 4, 5", "ADC input filter (A0-A3)"),
  (2, "Status LED + 470 Ω (optional)", "3 mm yellow LED, 1/4 W resistor", "—", "Sch. 5 note", "GPIO23 / GPIO24 filter/temp LEDs: on = active, blink = wire broken"),
 ]),
 ("SENSORS", [
  (0, "Hall-effect sensor (OPTIONAL)", "NPN, normally open, 6–36 V, M12", "NJK-5002C", "Sch. 5", "Not needed: this machine reads RPM from the ignition coil (board COIL input, rev 2.2+). Only for the Hall option"),
  (0, "Magnet (OPTIONAL)", "Neodymium, ~10 mm, + high-temp epoxy", "—", "Sch. 5", "Hall option only: on crank pulley; pulses_per_rev = 1"),
  (0, "Sensor bracket (OPTIONAL)", "Steel, holds Hall sensor 3–8 mm from magnet", "—", "Sch. 5", "Hall option only"),
  (2, "End-of-line resistor 4.7 kΩ", "1/2 W metal film, 1 %, 155 °C rated", "—", "Sch. 5", "One across each filter / temp switch, AT the switch. Seal in adhesive-lined heat-shrink."),
 ]),
 ("ALARM + SOUND", [
  (1, "Piezo alarm", "12 V, 100–110 dB, IP65+, panel mount", "—", "Sch. 6", "The horn: mount aimed at the operator"),
  (1, "N-MOSFET, logic-level", "IRLZ44N (TO-220) or AO3400 (SMD)", "IRLZ44N", "Sch. 6", "Or a 1-ch opto relay module instead"),
  (1, "Resistor 100 Ω", "1/4 W", "—", "Sch. 6", "MOSFET gate resistor"),
  (1, "Inline fuse holder + fuse", "Blade type, 1 A", "—", "Sch. 6", "Horn circuit"),
  (1, "Push button", "Momentary, panel mount, IP67", "—", "Sch. 6", "Silence button, GPIO 5. Glove-friendly size"),
  (1, "I2S amplifier board", "MAX98357A, 3 W, mono (or the stereo board)", "Adafruit 3006 (mono, J9) or 6513 (stereo, J16)", "Sch. 6", "Fit one only. dtoverlay=max98357a"),
  (4, "M2.5 standoff + 8 screws", "female-female, ~11 mm, for the amp board", "—", "Board README", "Mono uses 2 (H9-H10), stereo 4 (H11-H14)"),
  (1, "Speaker", "4 Ω, 3 W, weather-resistant", "—", "Sch. 6", "Startup chime + in-cab alert tones"),
  (1, "Rectifier diode (optional)", "1N4007", "1N4007", "Sch. 6", "Only with a coil horn or relay"),
 ]),
 ("BREAKOUT BOARD rev 2.4 (replaces the perfboard; key-off shutdown, light sensing, coil tach in its own HV corner)", [
  (1, "Bare PCB", "162 × 159 mm (rev 2.9), 2 layers, 1.6 mm, 1 oz", "breakout-board/fab gerbers zip", "Board README", "Most board makers sell a minimum of 5. Has the Project Moon Pi logo on top"),
  (1, "Board components kit", "Everything in breakout-board/fab/board-bom.csv", "—", "Board README", "Includes the resistors, diodes, optos and MOSFET listed above, plus the power-hold parts (IRF4905, CD4060, BC547 ×2)"),
  (1, "Pluggable terminal plugs", "5.08 mm: 5× 2-pin, 3× 3-pin, 1× 4-pin", "Phoenix MSTB 2,5/x-ST-5,08", "Board README", "Mate with the board's MSTBA headers"),
  (1, "40-pin IDC ribbon cable", "Female–female, 15–30 cm", "—", "Board README", "Pi GPIO to board J1, pin 1 to pin 1"),
  (1, "IC socket", "DIP-16, 7.62 mm", "—", "Board README", "Optional, for U6 (CD4060)"),
  (2, "Jumper shunt", "2.54 mm", "—", "Board README", "JP1 / JP2 fuel mode"),
 ]),
 ("LIGHTS (feed + sensing): see docs/lights-wiring.jpg", [
  (1, "Automotive relay", "12 V mini ISO, 4-pin, normally open, 30/40 A, WITH suppression diode", "—", "docs/lights-wiring.jpg", "Key ON/RUN drives the coil (86 = +, 85 = ground). Feeds the light switches"),
  (1, "Relay socket / pigtail", "Weatherproof, for a 4-pin mini ISO relay", "—", "docs/lights-wiring.jpg", "Or use a sealed fuse + relay box instead of this, the relay fuse and the two branch fuses"),
  (1, "Inline fuse holder + fuse", "Blade, 15 A (size for all the lights)", "—", "docs/lights-wiring.jpg", "Battery + to relay 30, within 18 in of the battery"),
  (1, "Inline fuse holder + fuse", "Blade, 3 A", "—", "docs/lights-wiring.jpg", "Key ON/RUN to relay 86 (coil)"),
  (2, "Inline fuse holder + fuse", "Blade, FRONT 10 A and REAR/WORK 7.5 A (size to your lights)", "—", "docs/lights-wiring.jpg", "Relay 87 to each switch. Fuse = watts ÷ 12 × 1.25"),
  (3, "Inline fuse holder + fuse", "Blade, 1 A", "—", "docs/lights-wiring.jpg", "One per sense wire (front, rear, work), at the tap on the lamp side of the switch"),
  (2, "Light switch", "≥15 A at 12 V DC, sealed: 1 × SPST on/off, 1 × SPDT ON-OFF-ON", "—", "docs/lights-wiring.jpg", "Front on/off; back up = rear, middle = off, down = work"),
 ]),
 ("MACHINE ANGLE (roll / pitch): README, Machine angle", [
  (1, "Accelerometer + gyro board", "LSM6DSOX 6-DoF, I2C, 3.3 V (or LSM6DS3TR-C, Adafruit 4503)", "Adafruit 4438", "README: Machine angle", "Mount rigidly to the frame, flat, X arrow forward. I2C address 0x6A"),
  (1, "Micro-Fit 3.0 receptacle housing", "4-position, single row, latching", "Molex 43645-0400", "Board README: TILT", "Plugs into the board's TILT header J13 (43650-0415)"),
  (4, "Micro-Fit 3.0 crimp pins", "Female, 20-24 AWG", "Molex 43030-0007", "Board README: TILT", "Crimp tool for Micro-Fit, or buy pre-crimped Micro-Fit leads"),
  (1, "Sensor cable", "22-24 AWG, 4-core, shielded if possible, under ~30-50 cm", "—", "README: Machine angle", "Your 14/16 AWG harness wire won't fit the Micro-Fit pins or the sensor board. Solder this end into the sensor board; shield to GND at the board end only"),
 ]),
 ("TEMPERATURE: README, Temperatures", [
  (2, "Waterproof temperature probe", "DS18B20 in a stainless tip, 3-wire cable (red 3V3, black GND, yellow/white data)", "—", "README: Temperatures", "One for the cab, one for outside air (shade it from sun and engine heat). Optional: the board measures the box itself"),
  (1, "Micro-Fit 3.0 receptacle housing", "3-position, single row, latching", "Molex 43645-0300", "Board README: TEMP PROBE", "Plugs into the board's TEMP PROBE header J14 (43650-0315)"),
  (3, "Micro-Fit 3.0 crimp pins", "Female, 20-24 AWG", "Molex 43030-0007", "Board README: TEMP PROBE", "Two probes: join their 3 wires in the cable (each wire to the same pin)"),
  (1, "Micro-Fit 3.0 receptacle housing", "8-position, single row, latching", "Molex 43645-0800", "Board README: BUTTON POD", "Plugs into the board's POD header J17 (43650-0815)"),
  (8, "Micro-Fit 3.0 crimp pins", "Female, 20-24 AWG", "Molex 43030-0007", "Board README: BUTTON POD", "8-core cable, board to the pod (buttons, SILENCE, GND, fan)"),
  (4, "Pushbutton head, black", "Eaton M22, 22 mm, momentary", "Eaton M22-D-S (flat-style head)", "enclosure/button-pod", "LEFT, RIGHT, OK, BACK"),
  (1, "Pushbutton head, red mushroom", "Eaton M22, 22 mm, momentary", "Eaton M22-DP-R", "enclosure/button-pod", "ALARM SILENCE"),
  (5, "Fixing adapter", "Eaton M22", "Eaton M22-A", "enclosure/button-pod", "One per button"),
  (5, "Contact block, 1 NO", "Eaton M22", "Eaton M22-K10", "enclosure/button-pod", "One per button"),
  (1, "Exhaust fan", "40 x 40 x 10 mm, 12 V", "any (two-wire)", "enclosure/button-pod", "Back wall of the pod; switched by the board (Q5)"),
  (1, "Cable gland", "M20, for the HDMI cable", "nylon or nickel-brass", "enclosure/button-pod", "Back wall of the pod"),
 ]),
 ("CHARGING: Delco 10SI 3-wire alternator (docs/wiring-schematic.jpg, section 7)", [
  (1, "Rectifier diode", "1N4001, 1 A 50 V", "1N4001", "Sch. 7", "In the terminal 1 (excite) wire, band toward the alternator: stops the running alternator back-feeding the key circuit (engine run-on, dash never sees key-off)"),
  (1, "Resistor 47 Ω", "5 W wirewound", "—", "Sch. 7", "In series with the diode: ~0.25 A with the key on and the engine stopped, like the charge lamp it replaces. Use the alternator maker's value if they give one"),
  (1, "Fusible link or circuit breaker", "Rated for the alternator (e.g. 60 A)", "—", "Sch. 7", "On the BAT stud wire, near the battery end. 8 AWG wire (10 AWG for 45 A units)"),
 ]),
 ("WIRING + ENCLOSURE", [
  (1, "Enclosure", "IP65+, fits Pi + interface boards", "—", "—", "Vibration-mount it"),
  (1, "Prototype board", "Perfboard / stripboard", "—", "—", "Only if hand-wiring instead of the breakout board"),
  (1, "Automotive wire", "18 AWG TXL/GXL, several colors", "—", "—", "Lot"),
  (1, "Sealed connectors", "Deutsch DT or Weatherpack assortment", "—", "—", "Avoid loose Dupont jumpers on the machine"),
  (1, "Screw terminal blocks", "PCB 5 mm pitch assortment", "—", "—", "Field wiring into the enclosure"),
  (1, "Heat-shrink + terminals", "Assortment", "—", "—", "Lot"),
  (1, "Display mount", "RAM-style ball mount or bracket", "—", "—", "With vibration damping"),
  (1, "Standoffs", "M2.5 nylon/brass set", "—", "—", "Mount the Pi and the plug-in modules"),
  (9, "M3 standoff + screws", "10 mm or taller, all the same height", "—", "Board README", "Breakout board mounting: 4 corners, 4 mid-sides, 1 centre (drilling template)"),
 ]),
 ("EXISTING MACHINE PARTS (reuse, check they work)", [
  (1, "Oil pressure switch", "Original, closes on low pressure", "—", "Sch. 5", "GPIO 22 via optocoupler"),
  (1, "Hydraulic filter bypass switch", "Original, closes on bypass", "—", "Sch. 5", "ADS1115 A2, monitored (4.7k EOL resistor at the switch)"),
  (1, "Hydraulic oil temp switch", "Original, closes when hot", "—", "Sch. 5", "ADS1115 A3, monitored (4.7k EOL resistor at the switch)"),
  (1, "Fuel sender", "Original, in tank", "—", "Sch. 4", "Calibrate with dash.py --calibrate"),
 ]),
]

HDR = ["Item", "Qty", "Part", "Value / Spec", "Example Part No.", "Used In", "Notes",
       "Unit Price (USD)", "Ext. Price (USD)", "Supplier", "Ordered"]
WIDTHS = [6, 6, 28, 38, 22, 13, 44, 15, 15, 16, 9]

thin = Side(style="thin", color="BFBFBF")
box = Border(left=thin, right=thin, top=thin, bottom=thin)
INPUT = PatternFill("solid", fgColor="FFFF00")
SECT = PatternFill("solid", fgColor="D9E1F2")
HEAD = PatternFill("solid", fgColor="1F3864")
money = '$#,##0.00;($#,##0.00);"-"'

ws["A1"] = "Bobcat Digital Dash — Bill of Materials"; ws["A1"].font = Font(name=F, size=16, bold=True)
ws["A2"] = "Matches docs/wiring-schematic.jpg (\"Sch. n\" = schematic section) and README.md."; ws["A2"].font = Font(name=F, size=10, italic=True, color="595959")
ws["A3"] = "How to use: enter prices in the yellow cells (e.g. 4.95); extended prices and totals update automatically. Mark Ordered with Y/N."
ws["A3"].font = Font(name=F, size=10); ws["A3"].fill = INPUT
ws.merge_cells("A3:K3")

r = 5
for c, h in enumerate(HDR, 1):
    cell = ws.cell(r, c, h); cell.font = Font(name=F, bold=True, color="FFFFFF"); cell.fill = HEAD
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True); cell.border = box
ws.row_dimensions[r].height = 30
first_data = r + 1
item = 0; subtotal_cells = []
dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True); ws.add_data_validation(dv)

for title, parts in SECTIONS:
    r += 1
    if title.startswith("EXISTING"):
        last_buy = r - 1          # the row above is the previous section's subtotal
    ws.cell(r, 1, title)
    for c in range(1, 12):
        ws.cell(r, c).fill = SECT; ws.cell(r, c).font = Font(name=F, bold=True); ws.cell(r, c).border = box
    s0 = r + 1
    for qty, part, spec, pn, used, notes in parts:
        r += 1; item += 1
        vals = [item, qty, part, spec, pn, used, notes]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v); cell.font = Font(name=F, color="0000FF" if c == 2 else "000000")
            cell.alignment = Alignment(vertical="top", wrap_text=True, horizontal="center" if c in (1, 2, 6) else "left")
        p = ws.cell(r, 8); p.fill = INPUT; p.number_format = money; p.font = Font(name=F, color="0000FF")
        e = ws.cell(r, 9, f"=B{r}*H{r}"); e.number_format = money; e.font = Font(name=F)
        ws.cell(r, 10).font = Font(name=F); ws.cell(r, 10).fill = INPUT
        o = ws.cell(r, 11); o.font = Font(name=F); o.fill = INPUT; o.alignment = Alignment(horizontal="center"); dv.add(o)
        for c in range(1, 12): ws.cell(r, c).border = box
    r += 1
    ws.cell(r, 7, f"Subtotal — {title.split(' (')[0].title()}").font = Font(name=F, italic=True)
    ws.cell(r, 7).alignment = Alignment(horizontal="right")
    st = ws.cell(r, 9, f"=SUM(I{s0}:I{r-1})"); st.number_format = money; st.font = Font(name=F, italic=True, bold=True)
    subtotal_cells.append(f"I{r}")

r += 2
ws.cell(r, 7, "TOTAL (all sections)").font = Font(name=F, bold=True, size=12)
ws.cell(r, 7).alignment = Alignment(horizontal="right")
t = ws.cell(r, 9, "=" + "+".join(subtotal_cells)); t.number_format = money; t.font = Font(name=F, bold=True, size=12)
t.border = Border(top=Side(style="thin"), bottom=Side(style="double"))
total_row = r
r += 1
ws.cell(r, 7, "Items still to order (excl. existing parts)").font = Font(name=F)
ws.cell(r, 7).alignment = Alignment(horizontal="right")
ws.cell(r, 9, f'=COUNTIF(B{first_data}:B{last_buy},">0")-COUNTIF(K{first_data}:K{last_buy},"Y")').font = Font(name=F)
r += 2
ws.cell(r, 1, "Notes: Qty in blue = quantity per machine. Existing machine parts usually cost $0 unless one needs replacing. "
              "Prices are left blank on purpose. Enter what you actually pay.").font = Font(name=F, size=9, italic=True, color="595959")

for i, w in enumerate(WIDTHS, 1):
    ws.column_dimensions[chr(64 + i)].width = w
ws.freeze_panes = "C6"
ws.auto_filter.ref = f"A5:K{total_row-2}"
ws.page_setup.orientation = "landscape"; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
ws.sheet_properties.pageSetUpPr.fitToPage = True
ws.print_title_rows = "5:5"
wb.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "bobcat-dash-BOM.xlsx"))
print("items", item, "total row", total_row)
