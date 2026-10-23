# Board generator

The KiCad schematic and PCB are generated from `design.py`, which lists every part and connection.
To change the board, edit `design.py` (and placement in `gen_pcb.py`), then run `./build.sh`. It
writes the schematic, places the parts, autoroutes with Freerouting, adds the ground fills, and
runs ERC, DRC and the schematic-parity check. The results go to `out/`.

**The schematic is drawn by hand-written layout code** in `gen_sch.py`: one function per block
(`blk_power`, `blk_hold`, `blk_inputs`, ...), placing each part and drawing its wires. Within a block
everything is wired; supplies use power symbols; signals between blocks use global labels. Before writing
the file, `gen_sch.py` traces every wire and checks it against `design.py`: a pin on the wrong net, a short,
or a net in two unconnected pieces stops the build with a message. So a new part in `design.py` also
needs a line in the right `blk_*` function, or the check will say its pins aren't wired.

`build.sh` then exports KiCad's netlist (`out/netlist.net`), and `gen_pcb.py` takes every pad's net name from
it. Short nets inside a block keep KiCad's automatic names (`Net-(R61-Pad2)`); the rest keep their
`design.py` names.

The logo on the back silkscreen comes from `logo_silk.json`, made by `make_logo_silk.py` from
`../../splash/logo-original.png` (needs numpy and Pillow). Its size and position are `LOGO_CENTRE` and
`LOGO_WIDTH` in `gen_pcb.py`. It has to stay clear of pads: run `./build.sh` and check DRC after moving it.

Needs KiCad 10 (at `/Applications/KiCad`) and Freerouting 2.x (`~/.local/bin/freerouting`, Java 25+).
