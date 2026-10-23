"""Bobcat dash breakout board: every part and every connection, in one place.
The schematic and PCB generators both read this file."""

FP_R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"
FP_LED = "LED_THT:LED_D3.0mm"
FP_D35 = "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal"
FP_D41 = "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"
FP_D15 = "Diode_THT:D_DO-15_P12.70mm_Horizontal"
FP_C = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
FP_DIP4 = "Package_DIP:DIP-4_W7.62mm"
FP_TO220 = "Package_TO_SOT_THT:TO-220-3_Vertical"
FP_FUSE = "Fuse:Fuseholder_Blade_Mini_Keystone_3568"
FP_TP = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"
FP_TP_GND = "TestPoint:TestPoint_Keystone_5005-5009_Compact"
FP_MH = "MountingHole:MountingHole_3.2mm_M3"
FP_MH25 = "MountingHole:MountingHole_2.7mm_M2.5"
FP_TO92 = "Package_TO_SOT_THT:TO-92_Inline_Wide"
FP_CP = "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm"
FP_DIP16 = "Package_DIP:DIP-16_W7.62mm"


def mstb(n):
    return f"Connector_Phoenix_MSTB:PhoenixContact_MSTBA_2,5_{n}-G-5,08_1x{n:02d}_P5.08mm_Horizontal"


PARTS = []   # dicts: ref, lib, value, fp, pins {num: net}, group, desc


def part(ref, lib, value, fp, pins, group, desc=""):
    PARTS.append(dict(ref=ref, lib=lib, value=value, fp=fp,
                      pins={str(k): v for k, v in pins.items()}, group=group, desc=desc))


R = lambda ref, val, a, b, grp, desc="": part(ref, "Device:R", val, FP_R, {1: a, 2: b}, grp, desc)
LED = lambda ref, a, k, grp, desc, color="green": part(ref, "Device:LED", f"LED_{color}", FP_LED, {2: a, 1: k}, grp, desc)
D = lambda ref, val, a, k, fp, grp, desc="": part(ref, "Device:D", val, fp, {2: a, 1: k}, grp, desc)
C = lambda ref, val, a, b, grp, desc="": part(ref, "Device:C", val, FP_C, {1: a, 2: b}, grp, desc)
TP = lambda ref, net, grp: part(ref, "Connector:TestPoint", net, FP_TP_GND if net == "GND" else FP_TP, {1: net}, grp, "test point")

# ---------------------------------------------------------------- Pi ribbon header (physical pin numbers)
PI = {1: "+3V3", 2: "+5V", 3: "SDA", 4: "+5V", 5: "SCL", 6: "GND", 7: "W1_DQ", 9: "GND", 11: "TACH_GPIO",
      12: "I2S_BCLK", 13: "HORN_GPIO", 14: "GND", 15: "OIL_GPIO", 16: "FILT_LED", 17: "+3V3",
      18: "TEMP_LED", 20: "GND", 22: "LT_FRONT_GPIO", 25: "GND", 29: "BTN_GPIO", 30: "GND", 31: "KEY_GPIO",
      32: "LT_REAR_GPIO", 33: "LT_WORK_GPIO", 34: "GND", 35: "I2S_LRC",
      36: "KILL_GPIO", 37: "HOLD_GPIO", 39: "GND", 40: "I2S_DIN"}
part("J1", "Connector_Generic:Conn_02x20_Odd_Even", "TO PI (40-pin ribbon)",
     "Connector_IDC:IDC-Header_2x20_P2.54mm_Vertical",
     {n: PI.get(n) for n in range(1, 41)}, "pi", "Box header, straight 40-pin IDC ribbon to the Pi GPIO header")

# ---------------------------------------------------------------- harness connectors (vehicle side)
part("J2", "Connector_Generic:Conn_01x03", "POWER IN", mstb(3), {1: "+12V_IN", 2: "IGN", 3: "GND"}, "power",
     "Constant battery +12V (fused at the battery), key switch IGN signal, chassis ground")
part("J3", "Connector_Generic:Conn_01x02", "TO 5V BUCK", mstb(2), {1: "+12V", 2: "GND"}, "power", "Switched, fused +12V out to the 12V->5V buck")
part("J4", "Connector_Generic:Conn_01x04", "SWITCHES", mstb(4), {1: "OIL_SW", 2: "FILT_SW", 3: "TEMP_SW", 4: "GND"}, "switch", "Engine oil pressure, hydraulic filter bypass, hydraulic oil temp switch wires")
part("J5", "Connector_Generic:Conn_01x03", "TACH", mstb(3), {1: "+12V", 2: "TACH_SIG", 3: "GND"}, "tach",
     "Hall sensor (brown +12V, black SIG, blue GND), if used instead of the coil input")
part("J12", "Connector_Generic:Conn_01x02", "COIL", mstb(2), {1: "COIL_IN", 2: "GND"}, "hv",
     "Ignition coil NEGATIVE terminal (high voltage spikes) + GND for a shielded wire's drain (rev 2.4)")
part("J6", "Connector_Generic:Conn_01x02", "FUEL", mstb(2), {1: "FUEL_IN", 2: "GND"}, "fuel", "Fuel sender")
part("J7", "Connector_Generic:Conn_01x02", "HORN", mstb(2), {1: "+12V_HORN", 2: "HORN_DRAIN"}, "horn", "Piezo alarm + and -")
part("J8", "Connector_Generic:Conn_01x02", "SILENCE", mstb(2), {1: "BTN_IN", 2: "GND"}, "button", "Silence push button")
part("J11", "Connector_Generic:Conn_01x03", "LIGHTS", mstb(3), {1: "LT_FRONT", 2: "LT_REAR", 3: "LT_WORK"}, "lights",
     "Sense wires from the lamp side of the front / rear / work light switches (a few mA each)")

# ---------------------------------------------------------------- plug-in modules
part("J9", "Connector_Generic:Conn_01x07", "MAX98357A MONO", "Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical",
     {1: "I2S_LRC", 2: "I2S_BCLK", 3: "I2S_DIN", 4: None, 5: None, 6: "GND", 7: "+5V"}, "audio",
     "Socket for the mono MAX98357A I2S amp board (Adafruit 3006): LRC BCLK DIN GAIN SD GND VIN")
# rev 2.8: or the stereo board (Adafruit 6513, two MAX98357As): different pin order, no SD. Fit one amp only.
part("J16", "Connector_Generic:Conn_01x06", "MAX98357A STEREO", "Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical",
     {1: "+5V", 2: "GND", 3: "I2S_BCLK", 4: "I2S_LRC", 5: "I2S_DIN", 6: None}, "audio",
     "Socket for the stereo MAX98357A amp board (Adafruit 6513): VDD GND BCLK LRC DIN GAIN. Fit J9 or J16, not both")
# rev 2.8: the current Adafruit ADS1115 (1085, STEMMA QT version) has two 6-pin rows 12.7 mm (0.5") apart, so it
# gets two sockets and plugs straight in. A+ / A- are the module's filtered analog supply: outputs, left open.
part("J10", "Connector_Generic:Conn_01x06", "ADS1115 PWR/I2C", "Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical",
     {1: "+3V3", 2: "GND", 3: "SCL", 4: "SDA", 5: "GND", 6: None}, "adc",
     "Socket for the ADS1115 board's bottom row: VIN GND SCL SDA ADDR ALRT (ADDR to GND: address 0x48)")
part("J15", "Connector_Generic:Conn_01x06", "ADS1115 INPUTS", "Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical",
     {1: None, 2: "TEMP_ADC", 3: "FILT_ADC", 4: "FUEL_ADC", 5: "BATT_ADC", 6: None}, "adc",
     "Socket for the ADS1115 board's top row: A+ A3 A2 A1 A0 A-")

# ---------------------------------------------------------------- power, fuses, protection, power LEDs
part("F1", "Device:Fuse", "5A", FP_FUSE, {1: "+12V_IN", 2: "+12V_BAT"}, "power", "Mini blade fuse: main feed")
part("F2", "Device:Fuse", "1A", FP_FUSE, {1: "+12V", 2: "+12V_HORN"}, "power", "Mini blade fuse: horn")
part("D1", "Device:D_Zener", "P6KE20A", FP_D15, {1: "+12V_BAT", 2: "GND"}, "power", "TVS: clamps spikes, blows F1 if wired backwards")
R("R1", "3.3k", "+12V", "PWR12_LED", "power"); LED("D2", "PWR12_LED", "GND", "power", "Board powered (+12V switched on)")
R("R2", "3.3k", "+12V_HORN", "PWRH_LED", "power"); LED("D3", "PWRH_LED", "GND", "power", "Horn feed present (F2 OK)")
R("R3", "1k", "+5V", "PWR5_LED", "power"); LED("D4", "PWR5_LED", "GND", "power", "+5V from Pi present")
R("R4", "470", "+3V3", "PWR33_LED", "power"); LED("D5", "PWR33_LED", "GND", "power", "+3.3V from Pi present")

# ---------------------------------------------------------------- optocoupler channels
# +12V -> 2.2k -> status LED -> opto LED -> switch wire (switch closes to chassis)
CHANNELS = [("OIL", "U1", 1), ("TACH", "U4", 4)]
for name, u, i in CHANNELS:
    sw = f"{name}_SW" if name != "TACH" else "TACH_SIG"
    grp = "tach" if name == "TACH" else "switch"
    R(f"R{10 + i}", "2.2k", "+12V", f"{name}_R", grp, "LED current, ~4 mA")
    LED(f"D{10 + i}", f"{name}_R", f"{name}_M", grp, f"{name} input active", "yellow")
    part(u, "Isolator:PC817", "PC817", FP_DIP4, {1: f"{name}_M", 2: sw, 3: "GND", 4: f"{name}_GPIO"}, grp, "Optocoupler")
    D(f"D{20 + i}", "1N4148", sw, f"{name}_R", FP_D35, grp, "Reverse-spike protection across the LEDs")
R("R15", "10k", "+3V3", "TACH_GPIO", "tach", "Tach pull-up (10k from rev 2.4: halves the current the PC817s must sink, for margin at low LED current)")

# ---------------------------------------------------------------- coil tach input (rev 2.2)
# Ignition coil negative terminal (PerTronix Ignitor + Flame-Thrower 40611, 3.0 ohm). It sits at ~1 V while
# the coil charges (dwell) and jumps to ~300-400 V when it fires, then settles at battery voltage.
# Two 2.2k 1/2 W resistors in series (each sees under 250 V) -> 15 V zener clamp + 1 uF filter
# -> 470 R -> yellow COIL LED -> PC817 -> GND. Coil open = LED on = TACH_GPIO low: one falling edge per spark.
# U10's output shares TACH_GPIO with U4 (Hall): wire one sensor or the other, not both.
# Rev 2.4: the coil wire has its own plug J12 on the left edge, and everything that sees the raw coil
# voltage (J12, R80, R81, plus the clamp D45/C11) sits in one boxed corner (group "hv").
part("R80", "Device:R", "2.2k 1/2W", "Resistor_THT:R_Axial_DIN0309_L9.0mm_D3.2mm_P12.70mm_Horizontal",
     {1: "COIL_IN", 2: "COIL_MID"}, "hv", "Coil input, first half (metal film, 350 V rated)")
part("R81", "Device:R", "2.2k 1/2W", "Resistor_THT:R_Axial_DIN0309_L9.0mm_D3.2mm_P12.70mm_Horizontal",
     {1: "COIL_MID", 2: "COIL_CLAMP"}, "hv", "Coil input, second half")
part("D45", "Device:D_Zener", "1N4744A", FP_D41, {1: "COIL_CLAMP", 2: "GND"}, "hv",
     "15 V 1 W zener: clamps the coil spike (and negative ringing to -0.7 V)")
C("C11", "1uF 50V", "COIL_CLAMP", "GND", "hv", "Filters the coil's ringing: one clean pulse per spark (ceramic, X7R)")
R("R82", "470", "COIL_CLAMP", "COIL_R", "tach", "LED current, ~2 mA")
LED("D39", "COIL_R", "COIL_M", "tach", "Coil input: on while the coil is not charging, flickers with the engine", "yellow")
part("U10", "Isolator:PC817", "PC817", FP_DIP4, {1: "COIL_M", 2: "GND", 3: "GND", 4: "TACH_GPIO"}, "tach",
     "Optocoupler: coil tach input")

# ---------------------------------------------------------------- monitored switches (filter, temp) -> A2, A3
# A 4.7k end-of-line resistor sits across each switch AT THE SWITCH (off the board).
# Board: 4.7k pull-up to 3.3V, so the wire reads ~1.65 V OK / ~0 V switch closed / 3.3 V wire broken.
# The Pi drives each channel's yellow LED: on = active, blinking = wire fault.
for name, i, adc in [("FILT", 2, "FILT_ADC"), ("TEMP", 3, "TEMP_ADC")]:
    k = 2 * (i - 2)
    R(f"R{50 + k}", "4.7k", "+3V3", f"{name}_SW", "switch", "Pull-up (pairs with the 4.7k at the switch)")
    R(f"R{51 + k}", "10k", f"{name}_SW", adc, "switch", "Series protection")
    D(f"D{34 + k}", "BAT85", adc, "+3V3", FP_D35, "switch", "Schottky clamp to 3.3V")
    D(f"D{35 + k}", "BAT85", "GND", adc, FP_D35, "switch", "Schottky clamp to GND")
    C(f"C{4 + (i - 2)}", "100nF", adc, "GND", "switch", "Filter")
    R(f"R{10 + i}", "470", f"{name}_LED", f"{name}_LK", "switch", "Status LED current")
    LED(f"D{10 + i}", f"{name}_LK", "GND", "switch", f"{name}: on = active, blink = wire fault (driven by the Pi)", "yellow")

# ---------------------------------------------------------------- horn driver
part("Q1", "Transistor_FET:IRLZ44N", "IRLZ44N", FP_TO220, {1: "HORN_G", 2: "HORN_DRAIN", 3: "GND"}, "horn", "Logic-level MOSFET, low-side switch")
R("R20", "100", "HORN_GPIO", "HORN_G", "horn", "Gate resistor")
R("R21", "10k", "HORN_G", "GND", "horn", "Pull-down: horn off while the Pi boots")
D("D25", "1N4007", "HORN_DRAIN", "+12V_HORN", FP_D41, "horn", "Flyback (coil horn / relay)")
R("R22", "3.3k", "+12V_HORN", "HORN_LR", "horn"); LED("D26", "HORN_LR", "HORN_DRAIN", "horn", "Horn output ON", "red")

# ---------------------------------------------------------------- battery voltage -> A0
R("R30", "47k", "+12V", "BATT_ADC", "batt", "Divider top (ratio 5.7)")
R("R31", "10k", "BATT_ADC", "GND", "batt", "Divider bottom")
C("C1", "100nF", "BATT_ADC", "GND", "batt", "Filter")
D("D30", "BAT85", "BATT_ADC", "+3V3", FP_D35, "batt", "Schottky clamp to 3.3V")
D("D31", "BAT85", "GND", "BATT_ADC", FP_D35, "batt", "Schottky clamp to GND")

# ---------------------------------------------------------------- fuel sender -> A1
# JP1 1-2 = option A (sender only, with JP2 fitted: 220R pull-up)
# JP1 2-3 = option B (original gauge kept: 47k/10k divider, JP2 off)
R("R32", "220", "+3V3", "FUEL_PU", "fuel", "Sender pull-up (option A)")
part("JP2", "Jumper:Jumper_2_Open", "PULL-UP (A only)", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
     {1: "FUEL_PU", 2: "FUEL_SEL"}, "fuel", "Fit for option A")
part("JP1", "Jumper:Jumper_3_Open", "A=1-2  B=2-3", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
     {1: "FUEL_IN", 2: "FUEL_SEL", 3: "FUEL_DIV"}, "fuel", "Fuel mode select")
R("R33", "47k", "FUEL_IN", "FUEL_DIV", "fuel", "Divider top (option B)")
R("R34", "10k", "FUEL_DIV", "GND", "fuel", "Divider bottom (option B)")
R("R35", "1k", "FUEL_SEL", "FUEL_ADC", "fuel", "Series protection")
C("C2", "100nF", "FUEL_ADC", "GND", "fuel", "Filter")
D("D32", "BAT85", "FUEL_ADC", "+3V3", FP_D35, "fuel", "Schottky clamp to 3.3V")
D("D33", "BAT85", "GND", "FUEL_ADC", FP_D35, "fuel", "Schottky clamp to GND")

# ---------------------------------------------------------------- aux analog + silence button
R("R40", "1k", "BTN_IN", "BTN_GPIO", "button", "Series protection")
C("C3", "100nF", "BTN_GPIO", "GND", "button", "Debounce / noise filter")

# ---------------------------------------------------------------- power hold (rev 2.0)
# +12V_BAT (constant, after F1) -> Q2 P-MOSFET -> +12V (everything else). Q2 is on while Q3 conducts.
# Q3 conducts if the key is on (IGN) OR the Pi holds HOLD high (set in config.txt at boot).
# Q4 overrides both and cuts power: driven by the Pi's KILL pin at the very end of shutdown,
# or by the U6 timer if the Pi hasn't shut down ~3 minutes after key-off. C7 keeps Q4 on for
# a few seconds, so if the key is already back on, the Pi gets a clean power cycle and reboots.
part("Q2", "Transistor_FET:IRF4905", "IRF4905", FP_TO220, {1: "Q2_G", 2: "+12V", 3: "+12V_BAT"}, "hold",
     "P-MOSFET high-side power switch, -55 V 74 A 20 mOhm")
R("R60", "47k", "+12V_BAT", "Q2_G", "hold", "Gate pull-up: Q2 off by default")
part("D40", "Device:D_Zener", "BZX79C15", FP_D35, {1: "+12V_BAT", 2: "Q2_G"}, "hold", "15 V zener: limits gate-source voltage")
R("R61", "4.7k", "Q2_G", "Q3_C", "hold", "Gate drive (Vgs ~ -11 V)")
part("Q3", "Transistor_BJT:BC547", "BC547B", FP_TO92, {1: "Q3_C", 2: "PWR_ON", 3: "GND"}, "hold", "Turns Q2 on")
R("R62", "47k", "IGN", "PWR_ON", "hold", "Key on -> power on")
R("R63", "10k", "HOLD_GPIO", "PWR_ON", "hold", "Pi HOLD -> power on")
R("R64", "100k", "PWR_ON", "GND", "hold", "Pull-down")
part("Q4", "Transistor_BJT:BC547", "BC547B", FP_TO92, {1: "PWR_ON", 2: "KILL_B", 3: "GND"}, "hold", "Power cut: overrides key and HOLD")
R("R65", "100k", "KILL_RC", "KILL_B", "hold", "Q4 base (~20 uA: saturates Q4 with margin)")
R("R66", "1M", "KILL_RC", "GND", "hold", "Discharge")
part("C7", "Device:C_Polarized", "10uF 25V", FP_CP, {1: "KILL_RC", 2: "GND"}, "hold", "Stretches a power cut to a few seconds")
R("R67", "1k", "KILL_GPIO", "KILL_A", "hold", "Series")
D("D41", "1N4148", "KILL_A", "KILL_RC", FP_D35, "hold", "Pi KILL -> power cut")
R("R68", "1k", "TMR_Q14", "TMR_A", "hold", "Series")
D("D42", "1N4148", "TMR_A", "KILL_RC", FP_D35, "hold", "Timer -> power cut")
# U6: CD4060 counter + RC oscillator (~45 Hz). Held in reset while the key is on.
# Q14 goes high 8192 cycles (~3 minutes) after key-off.
part("U6", "4xxx:4060", "CD4060BE", FP_DIP16,
     {1: None, 2: None, 3: "TMR_Q14", 4: None, 5: None, 6: None, 7: None, 8: "GND", 9: "TMR_CT", 10: "TMR_RT",
      11: "TMR_RS", 12: "TMR_RST", 13: None, 14: None, 15: None, 16: "TMR_VDD"}, "hold",
     "Key-off watchdog timer: cuts power ~3 min after key-off if the Pi hasn't")
R("R69", "220k", "TMR_RS", "TMR_N", "hold", "Oscillator input resistor")
R("R70", "100k", "TMR_RT", "TMR_N", "hold", "Timing resistor")
C("C8", "100nF film", "TMR_CT", "TMR_N", "hold", "Timing capacitor (film for accuracy)")
R("R71", "470", "+12V", "TMR_VDD", "hold", "Supply")
part("D43", "Device:D_Zener", "BZX79C10", FP_D35, {1: "TMR_VDD", 2: "GND"}, "hold", "10 V supply for U6")
C("C9", "100nF", "TMR_VDD", "GND", "hold", "Decoupling")
R("R72", "10k", "IGN", "TMR_RST", "hold", "Key on -> timer reset")
R("R73", "100k", "TMR_RST", "GND", "hold", "Pull-down")
C("C10", "100nF", "TMR_RST", "GND", "hold", "Filter")
# key sense -> Pi: IGN -> 2.2k -> KEY LED -> PC817 -> GND. Key on = GPIO 6 low.
R("R16", "2.2k", "IGN", "KEY_R", "hold", "LED current, ~4 mA")
LED("D16", "KEY_R", "KEY_M", "hold", "Key on", "yellow")
part("U5", "Isolator:PC817", "PC817", FP_DIP4, {1: "KEY_M", 2: "GND", 3: "GND", 4: "KEY_GPIO"}, "hold", "Optocoupler: key sense")
D("D27", "1N4007", "GND", "IGN", "Diode_THT:D_DO-41_SOD81_P7.62mm_Horizontal", "hold", "Clamps negative spikes on the IGN wire")
R("R74", "470", "HOLD_GPIO", "HOLD_LK", "hold", "LED current")
LED("D17", "HOLD_LK", "GND", "hold", "Pi is holding power on", "green")
# schematic-only power flags (no footprint): U6 is the first part with power-input pins
part("#FLG01", "power:PWR_FLAG", "PWR_FLAG", None, {1: "TMR_VDD"}, "hold")
part("#FLG02", "power:PWR_FLAG", "PWR_FLAG", None, {1: "GND"}, "hold")

# ---------------------------------------------------------------- light sensing (rev 2.1)
# Lamp side of each light switch -> 2.2k -> yellow status LED -> PC817 -> GND.
# Light on = LED lit = GPIO pulled low. Only a few mA flow: the lamps' own current never comes here.
for name, i, u, dz in [("FRONT", 7, "U7", "D28"), ("REAR", 8, "U8", "D29"), ("WORK", 9, "U9", "D38")]:
    R(f"R{10 + i}", "2.2k", f"LT_{name}", f"LT_{name}_R", "lights", "LED current, ~4 mA")
    LED(f"D{11 + i}", f"LT_{name}_R", f"LT_{name}_M", "lights", f"{name.title()} light on", "yellow")
    part(u, "Isolator:PC817", "PC817", FP_DIP4, {1: f"LT_{name}_M", 2: "GND", 3: "GND", 4: f"LT_{name}_GPIO"}, "lights",
         f"Optocoupler: {name.lower()} light sense")
    D(dz, "1N4148", "GND", f"LT_{name}_R", "Diode_THT:D_DO-35_SOD27_P2.54mm_Vertical_AnodeUp", "lights",
      "Reverse-spike protection across the LEDs (standing diode)")

# ---------------------------------------------------------------- tilt sensor header (rev 2.5)
# LSM6DSOX accelerometer + gyro board (Adafruit 4438) on the same I2C bus as the ADS1115, by a short cable.
# Rev 2.6: a latching Molex Micro-Fit 3.0 header (vibration can't shake the plug out); the cable is soldered
# to the sensor board (its STEMMA QT socket is friction-only). Pins 1-4: GND, 3V3, SDA, SCL.
# 100R in SDA / SCL: static and wiring-mistake protection, and they soften noise picked up on the cable.
# 47R in the 3.3 V feed: a shorted cable draws <= 70 mA (within the resistor's 1/4 W), so the Pi's 3.3 V rail
# (which also feeds the ADS1115) stays up. The sensor board draws ~3 mA: it still gets ~3.2 V.
part("J13", "Connector_Generic:Conn_01x04", "TILT", "Connector_Molex:Molex_Micro-Fit_3.0_43650-0415_1x04_P3.00mm_Vertical",
     {1: "GND", 2: "TILT_3V3", 3: "TILT_SDA", 4: "TILT_SCL"}, "tilt",
     "Molex Micro-Fit 3.0 43650-0415 (latching). Mates with housing 43645-0400 + 43030-0007 pins. Tilt sensor: GND, 3V3, SDA, SCL; cable under ~30-50 cm")
R("R83", "100", "SDA", "TILT_SDA", "tilt", "SDA series protection")
R("R84", "100", "SCL", "TILT_SCL", "tilt", "SCL series protection")
R("R85", "47", "+3V3", "TILT_3V3", "tilt", "Sensor supply: limits a shorted cable to ~70 mA")

# ---------------------------------------------------------------- temperature (rev 2.7)
# 1-Wire bus on GPIO 4 (Pi pin 7, the Pi's standard 1-Wire pin: dtoverlay=w1-gpio). DS18B20s, +-0.5 C, -55..125 C.
#  * U11 on the board: the breakout box's air temperature (BOX HOT warnings).
#  * J14: latching 3-pin connector for external waterproof DS18B20 probes (cab, outside air). Several probes
#    can share it (each has its own ID). 100R in the probe's data line and 47R in its 3.3 V feed protect the
#    Pi and its 3.3 V rail from a damaged probe cable, as on the TILT connector.
part("U11", "Sensor_Temperature:DS18B20", "DS18B20", "Package_TO_SOT_THT:TO-92_Inline_Wide",
     {1: "GND", 2: "W1_DQ", 3: "+3V3"}, "temp", "Board / box air temperature (1-Wire)")
R("R86", "4.7k", "W1_DQ", "+3V3", "temp", "1-Wire pull-up")
part("J14", "Connector_Generic:Conn_01x03", "TEMP PROBE", "Connector_Molex:Molex_Micro-Fit_3.0_43650-0315_1x03_P3.00mm_Vertical",
     {1: "GND", 2: "PROBE_DQ", 3: "PROBE_3V3"}, "temp",
     "Molex Micro-Fit 3.0 43650-0315 (latching): external DS18B20 probes: 1 GND, 2 DQ, 3 3V3. Housing 43645-0300")
R("R87", "100", "W1_DQ", "PROBE_DQ", "temp", "Probe data series protection")
R("R88", "47", "+3V3", "PROBE_3V3", "temp", "Probe supply: limits a shorted probe cable")

# ---------------------------------------------------------------- test points
TPS = ["+12V_IN", "+12V", "+12V_HORN", "+5V", "+3V3", "GND", "GND", "GND", "BATT_ADC", "FUEL_ADC",
       "OIL_GPIO", "FILT_SW", "TEMP_SW", "TACH_GPIO", "HORN_G", "BTN_GPIO"]
TPS += ["+12V_BAT", "IGN", "HOLD_GPIO", "KILL_RC"]     # rev 2.0: power hold
for i, n in enumerate(TPS, 1):
    TP(f"TP{i}", n, "tp")

for i in range(1, 5):
    part(f"H{i}", "Mechanical:MountingHole", "M3", FP_MH, {}, "mech", "Mounting hole")
# rev 2.8: the ADS1115 module's four corner holes (M2.5), so it can be screwed down on 11 mm standoffs
for i in range(5, 9):
    part(f"H{i}", "Mechanical:MountingHole", "M2.5", FP_MH25, {}, "mech",
         "ADS1115 module standoff hole")
# rev 2.8: more board mounting holes (M3), near the middle of each side, against vibration
for i in range(15, 20):
    part(f"H{i}", "Mechanical:MountingHole", "M3", FP_MH, {}, "mech",
         "Mounting hole (middle of a side)" if i < 19 else "Mounting hole (near the centre)")
# rev 2.8: amp board standoffs: H9-H10 mono (Adafruit 3006), H11-H14 stereo (Adafruit 6513)
for i in range(9, 15):
    part(f"H{i}", "Mechanical:MountingHole", "M2.5", FP_MH25, {}, "mech",
         "Mono amp board standoff hole" if i < 11 else "Stereo amp board standoff hole")

# Net classes: (track width mm, clearance mm)
NETCLASSES = {
    "Power": (2.0, 0.4, ["+12V_IN", "+12V_BAT"]),
    "Switched": (1.2, 0.4, ["+12V"]),      # <= 2.5 A (Pi 5 at full load), ~10 C rise on 1 oz
    "Ground": (1.0, 0.3, ["GND"]),          # plus a ground fill on both layers
    "Horn": (1.0, 0.4, ["+12V_HORN", "HORN_DRAIN"]),
    "Supply": (0.6, 0.3, ["+5V", "+3V3"]),
    "HighVolt": (0.5, 1.2, ["COIL_IN", "COIL_MID"]),   # coil spikes up to ~400 V: wide spacing
}
DEFAULT_TRACK, DEFAULT_CLEAR = 0.4, 0.3


def nets():
    out = {}
    for p in PARTS:
        for num, net in p["pins"].items():
            if net:
                out.setdefault(net, []).append((p["ref"], num))
    return out


if __name__ == "__main__":
    n = nets()
    print(len(PARTS), "parts,", len(n), "nets")
    single = {k: v for k, v in n.items() if len(v) < 2}
    print("nets with only one pin:", single or "none")
