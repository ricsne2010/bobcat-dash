"""CHT + parking brake board (rev 1.0): sits in the electronics box beside the breakout board, on its AUX plug (J18).

* Four sockets for Adafruit MCP9601 thermocouple amplifier modules (product 5165): one per cylinder. Each
  module's own screw terminal takes the Type K thermocouple (or Type K extension wire): that's where the
  thermocouple metal meets copper, right beside the chip that measures its temperature (cold junction).
  Fit only the modules you need. The socket sets the module's I2C address with its ADDR pin, the same way the
  module's own 22k / 43k jumpers do: socket 1 to GND = 0x60, 2 through 22k = 0x65, 3 through 43k = 0x66,
  4 open = 0x67. Leave the modules' address jumpers open.
* The parking brake input: +12V (through 2.2k on the breakout board) -> BRAKE SET LED -> PC817 LED -> brake
  switch wire; the switch closes to chassis when the brake is set = GPIO 9 low. Like the breakout board's oil
  pressure input.

Module pinout (Adafruit-MCP9601-PCB, header JP3, left to right with the header at the bottom):
  VIN GND SCL SDA ALERT1 ALERT2 ALERT3 ALERT4 ADDR. Module 25.4 x 17.8 mm, M2.5 holes 2.54 mm in from the
  corners on the terminal-block edge. The modules stand on their headers in the sockets: 11 mm M2.5 standoffs.

Shared by gen_sch.py (schematic) and gen_pcb.py (board).
"""
NAME = "cht-board"
REV = "1.0"

MSTB2 = "Connector_Phoenix_MSTB:PhoenixContact_MSTBA_2,5_2-G-5,08_1x02_P5.08mm_Horizontal"
SOCKET9 = "Connector_PinSocket_2.54mm:PinSocket_1x09_P2.54mm_Vertical"
FP_R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"
FP_LED = "LED_THT:LED_D3.0mm"
FP_D35 = "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal"
FP_DIP4 = "Package_DIP:DIP-4_W7.62mm"

MODULE_PINS = ["VIN", "GND", "SCL", "SDA", "AL1", "AL2", "AL3", "AL4", "ADDR"]
ADDR = {1: "GND", 2: "ADDR2", 3: "ADDR3", 4: None}            # socket -> what its ADDR pin goes to
ADDRESS = {1: "0x60", 2: "0x65", 3: "0x66", 4: "0x67"}

# ref: (symbol, value, footprint, {pin: net or None}, description)
PARTS = {
    "J1": ("Connector_Generic:Conn_02x03_Odd_Even", "AUX TO BREAKOUT J18",
           "Connector_Molex:Molex_Micro-Fit_3.0_43045-0612_2x03_P3.00mm_Vertical",
           {1: "GND", 2: "+3V3", 3: "SDA", 4: "SCL", 5: "BRAKE", 6: "BRAKE_12V"},
           "Molex Micro-Fit 3.0 43045-0612 2x3 (latching): to the breakout board's AUX plug J18, pin to pin. "
           "1 GND, 2 3V3, 3 SDA, 4 SCL, 5 BRAKE (GPIO 9), 6 BRAKE 12V. Housing 43025-0600 both ends"),
    "J2": ("Connector_Generic:Conn_01x02", "PARK BRAKE", MSTB2, {1: "BRK_SW", 2: "GND"},
           "Phoenix MSTB 2-pin: parking brake switch (closed = brake set) between SW and GND"),
    "U1": ("Isolator:PC817", "PC817", FP_DIP4, {1: "BRK_M", 2: "BRK_SW", 3: "GND", 4: "BRAKE"},
           "Optocoupler: parking brake input"),
    "D1": ("Device:LED", "LED_green", FP_LED, {2: "BRAKE_12V", 1: "BRK_M"}, "BRAKE SET: lit while the brake is set"),
    "D2": ("Device:D", "1N4148", FP_D35, {2: "BRK_SW", 1: "BRAKE_12V"}, "Reverse-spike protection across the LEDs"),
    "R1": ("Device:R", "22k", FP_R, {1: "ADDR2", 2: "GND"}, "Socket 2 address: 0x65"),
    "R2": ("Device:R", "43k", FP_R, {1: "ADDR3", 2: "GND"}, "Socket 3 address: 0x66"),
}
for n in range(1, 5):
    pins = {1: "+3V3", 2: "GND", 3: "SCL", 4: "SDA", 5: None, 6: None, 7: None, 8: None, 9: ADDR[n]}
    PARTS[f"M{n}"] = ("Connector_Generic:Conn_01x09", f"CYL {n} MCP9601", SOCKET9, pins,
                      f"Socket for an Adafruit MCP9601 module (5165): cylinder {n}, I2C {ADDRESS[n]}. "
                      "VIN GND SCL SDA ALERT1-4 ADDR")
for i in range(1, 5):
    PARTS[f"H{i}"] = ("Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", {}, "Board mounting hole")
for i in range(5, 13):
    PARTS[f"H{i}"] = ("Mechanical:MountingHole", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", {},
                      "Standoff hole for an MCP9601 module (11 mm M2.5 standoff)")

# ---------------------------------------------------------------- geometry (mm, y down)
W, H = 87.0, 46.0
MW, MH = 25.4, 17.78                        # module outline
# module top-left corners; "flip" = turned round so its header faces the middle of the board and its
# thermocouple terminal faces the board's edge (top row: terminals up, bottom row: terminals down)
MODULES = {1: (7.5, 3.0, False), 2: (36.4, 3.0, False), 3: (7.5, H - 3.0 - MH, True), 4: (36.4, H - 3.0 - MH, True)}


def module_pin(n, k):
    """Socket n's pin k (1 = VIN ... 9 = ADDR) position."""
    ox, oy, flip = MODULES[n]
    if flip:
        return ox + MW - 2.667 - 2.54 * (k - 1), oy + 2.54
    return ox + 2.667 + 2.54 * (k - 1), oy + 15.24


def module_holes(n):
    ox, oy, flip = MODULES[n]
    y = oy + (15.24 if flip else 2.54)
    return [(ox + 2.54, y), (ox + 22.86, y)]


BOARD_HOLES = [(3.5, 3.5), (W - 3.5, 3.5), (3.5, H - 3.5), (W - 3.5, H - 3.5)]
HOLES = BOARD_HOLES + [h for n in range(1, 5) for h in module_holes(n)]

# parts in the right-hand strip (x 63-87): pin 1 positions (rotations in gen_pcb). J2's plug faces the right edge.
STRIP = {"J1": (66.5, 7.0), "U1": (64.5, 21.8), "D1": (64.5, 28.6), "D2": (64.5, 33.6), "J2": (W - 10.5, 34.5)}
R_AT = {"R1": (52.0, 22.9, 0), "R2": (10.5, 22.9, 0)}       # in the gap between the module rows, by their sockets
LOGO_CENTRE, LOGO_WIDTH = (68.0, 40.8), 8.0
