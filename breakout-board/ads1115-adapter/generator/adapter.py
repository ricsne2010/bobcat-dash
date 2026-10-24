"""ADS1115 adapter (rev 1.0): lets a 10-pin inline ADS1115 board plug into the breakout board's two-row socket.

The breakout board (rev 2.8) takes the current Adafruit 1085 (STEMMA QT) directly: two 6-pin rows 12.7 mm apart
(J15: A+ A3 A2 A1 A0 A-, J10: VIN GND SCL SDA ADDR ALRT). The older Adafruit 1085 and nearly every clone have one
10-pin row instead: VDD GND SCL SDA ADDR ALRT A0 A1 A2 A3. This board has male pins underneath in the two-row
pattern, the same four M2.5 standoff holes, and a 10-pin socket on top. Straight-through wiring: no software change.

Shared by gen_sch.py (schematic) and gen_pcb.py (board).
"""
NAME = "ads1115-adapter"
REV = "1.1"

# ref: (symbol, value, footprint, {pin: net or None}, description)
PARTS = {
    "J1": ("Connector_Generic:Conn_01x06", "TO BOARD J15",
           "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
           {1: None, 2: "A3", 3: "A2", 4: "A1", 5: "A0", 6: None},
           "Male pins underneath, into the breakout board's J15 (A+ A3 A2 A1 A0 A-). A+ / A- not used"),
    "J2": ("Connector_Generic:Conn_01x06", "TO BOARD J10",
           "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
           {1: "VDD", 2: "GND", 3: "SCL", 4: "SDA", 5: "ADDR", 6: "ALRT"},
           "Male pins underneath, into the breakout board's J10 (VIN GND SCL SDA ADDR ALRT)"),
    "J3": ("Connector_Generic:Conn_01x10", "ADS1115 10-PIN",
           "Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical",
           {1: "VDD", 2: "GND", 3: "SCL", 4: "SDA", 5: "ADDR", 6: "ALRT", 7: "A0", 8: "A1", 9: "A2", 10: "A3"},
           "Socket on top for a 10-pin ADS1115 board: VDD GND SCL SDA ADDR ALRT A0 A1 A2 A3"),
}
for i in range(1, 5):
    PARTS[f"H{i}"] = ("Mechanical:MountingHole", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", {},
                      "Standoff hole, lines up with the breakout board's H5-H8")
for i in (5, 6):
    PARTS[f"H{i}"] = ("Mechanical:MountingHole", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", {},
                      "Standoff hole for the 10-pin ADS1115 board itself (original Adafruit layout)")

# Board geometry (mm, y down). Rows 12.7 mm apart like the Adafruit 1085; the 10-pin socket sits between them.
# The right-hand 12 mm is a strip for the Project Moon Pi logo (top and back). On the breakout board that side sits over
# the empty space between the ADC module and the TEMP column.
W, H = 42.0, 24.7                     # 5 mm added on top (rev 1.1) for the 10-pin board's own holes
CX = 15.0                             # centre line of the pin rows and holes
LOGO_CENTRE, LOGO_WIDTH = (36.0, H / 2), 11.0
ROW_A, ROW_P = 8.5, 8.5 + 12.7        # J1 (analog row, top), J2 (power row, bottom): same order as on the board
ROW_S = (ROW_A + ROW_P) / 2           # J3 socket
HOLES = [(CX - 10.16, ROW_A), (CX + 10.16, ROW_A), (CX - 10.16, ROW_P), (CX + 10.16, ROW_P),
         # H5, H6: the 10-pin board's two holes, on its far edge: 12.7 mm from its row, in line with pins 1 and 10
         (CX - 11.43, ROW_S - 12.7), (CX + 11.43, ROW_S - 12.7)]
PIN1 = {"J1": (CX - 6.35, ROW_A), "J2": (CX - 6.35, ROW_P), "J3": (CX - 11.43, ROW_S)}
BACK = {"J1", "J2"}                   # header bodies under the board, pins pointing down

LABELS_A = ["A+", "A3", "A2", "A1", "A0", "A-"]
LABELS_P = ["VIN", "GND", "SCL", "SDA", "ADDR", "ALRT"]
LABELS_S = ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"]
