"""Stage 3: give a solid zone connection to any GND pad DRC reports as a starved thermal."""
import json, subprocess, sys
import pcbnew
PCB = sys.argv[1]
K = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
for attempt in range(3):
    subprocess.run([K, "pcb", "drc", "--format", "json", "-o", "thermal.json", PCB], capture_output=True)
    starved = [v for v in json.load(open("thermal.json"))["violations"] if v["type"] == "starved_thermal"]
    if not starved:
        print("no starved thermals"); break
    board = pcbnew.LoadBoard(PCB)
    for v in starved:
        for it in v["items"]:
            d = it["description"]                      # "PTH pad 9 [GND] of J1"
            if " pad " in d and " of " in d:
                num = d.split(" pad ")[1].split(" ")[0]; ref = d.split(" of ")[-1]
                for pad in board.FindFootprintByReference(ref).Pads():
                    if pad.GetNumber() == num:
                        pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
                        print("solid zone connection:", ref, "pad", num)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
