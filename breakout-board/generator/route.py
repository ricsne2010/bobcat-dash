"""Stage 2: autoroute with Freerouting, then add ground fills. Run with KiCad's Python."""
import os
import random
import subprocess
import sys

import pcbnew

PCB = sys.argv[1]
MM = pcbnew.FromMM

def shuffle_nets(path, seed):
    """Freerouting is deterministic: the same .dsn always routes the same way. Its result depends on the order
    of the nets, though, so each new attempt gets the nets in a different (seeded, repeatable) order."""
    lines = open(path).read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip() == "(network")
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("    (class "))
    blocks, cur = [], []
    for l in lines[start + 1:end]:
        cur.append(l)
        if l == "    )":
            blocks.append(cur)
            cur = []
    assert not cur, "unexpected .dsn layout"
    random.Random(seed).shuffle(blocks)
    lines[start + 1:end] = [l for b in blocks for l in b]
    open(path, "w").write("\n".join(lines))


best = None
ATTEMPTS = int(os.environ.get("ROUTE_ATTEMPTS", "12"))
for attempt in range(1, ATTEMPTS + 1):
    board = pcbnew.LoadBoard(PCB)
    assert pcbnew.ExportSpecctraDSN(board, "route.dsn"), "DSN export failed"
    if attempt > 1:
        shuffle_nets("route.dsn", attempt)
    # Freerouting's own messages go to out/route.log: watch it with  tail -f out/route.log
    # (no window: with its GUI on, Freerouting 2.5 routes but never saves the result)
    with open(os.path.join(os.path.dirname(os.path.abspath(PCB)), "route.log"), "a") as log:
        log.write(f"\n===== routing attempt {attempt} =====\n"); log.flush()
        r = subprocess.run([os.path.expanduser("~/.local/bin/freerouting"), "-de", "route.dsn", "-do", "route.ses",
                            "--router.autorouter.max_passes=200", "--router.automatic_neckdown=false",
                            "--gui.enabled=false"],
                           stdout=log, stderr=subprocess.STDOUT, text=True, timeout=1800)
    assert pcbnew.ImportSpecctraSES(board, "route.ses"), "SES import failed"
    board.BuildConnectivity()
    left = board.GetConnectivity().GetUnconnectedCount(False)
    print(f"routing attempt {attempt}: {left} connection(s) left unrouted", flush=True)
    if best is None or left < best[0]:
        best = (left, board)
    if left == 0:
        break
left, board = best

# ground fill on both copper layers
gnd = board.FindNet("GND") or board.FindNet("/GND")
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET(); ls.AddLayer(layer); z.SetLayerSet(ls); z.SetNet(gnd)
    z.SetLocalClearance(MM(0.4)); z.SetMinThickness(MM(0.3))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.4)); z.SetThermalReliefSpokeWidth(MM(0.6))
    ol = z.Outline(); ol.NewOutline()
    bb = board.GetBoardEdgesBoundingBox()
    W, H = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
    for x, y in [(0.6, 0.6), (W - 0.6, 0.6), (W - 0.6, H - 0.6), (0.6, H - 0.6)]:
        ol.Append(MM(x), MM(y))
    board.Add(z)
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(PCB, board)
print("routed + filled:", PCB, "tracks:", len(board.GetTracks()))
