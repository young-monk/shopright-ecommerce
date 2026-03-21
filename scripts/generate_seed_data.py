"""
Generate ~1000 realistic home improvement products for ShopRight.
Outputs to infra/sql/seeds.sql
Run: python scripts/generate_seed_data.py
"""

import json
import random
import math
from pathlib import Path

random.seed(42)

# ── Brand & Category definitions ──────────────────────────────────────────────

CATALOG = {
    "Power Tools": {
        "brands": ["DEWALT", "Milwaukee", "Makita", "Bosch", "Ryobi", "Ridgid", "Metabo HPT", "Skil"],
        "products": [
            {
                "name": "{brand} {v}V Cordless Drill Driver Kit",
                "desc": "Professional cordless drill with {v}V battery system. {c}+1 clutch settings, 1/2-inch keyless chuck. Kit includes 2 batteries, charger, and carrying bag.",
                "price_range": (79, 299),
                "specs": lambda v, b: {"voltage": f"{v}V", "chuck_size": "1/2 inch", "clutch_settings": f"{random.choice([15,20,24])}+1", "max_torque": f"{random.randint(280,500)} UWO", "weight": f"{random.uniform(2.8,4.5):.1f} lbs"},
                "vars": [("v", [12, 18, 20, 24]), ("c", [15, 20, 24])],
            },
            {
                "name": "{brand} {v}V Cordless Impact Driver",
                "desc": "Compact impact driver with {v}V battery. 3-speed settings, LED work light. 1/4-inch hex chuck. Up to {t} in-lbs of torque.",
                "price_range": (69, 249),
                "specs": lambda v, t: {"voltage": f"{v}V", "max_torque": f"{t} in-lbs", "speeds": "3", "chuck": "1/4 inch hex", "impacts_per_min": f"{random.randint(3400,4000)}"},
                "vars": [("v", [12, 18, 20]), ("t", [1500, 1700, 1800, 2000])],
            },
            {
                "name": "{brand} {s}-Inch Circular Saw",
                "desc": "Cordless circular saw with {s}-inch blade. Bevel cuts up to 50°. Electric brake, {rpm} RPM no-load speed.",
                "price_range": (99, 349),
                "specs": lambda s, rpm: {"blade_size": f"{s} inch", "no_load_rpm": str(rpm), "bevel": "0-50 degrees", "weight": f"{random.uniform(5.5,8.0):.1f} lbs"},
                "vars": [("s", ["6-1/2", "7-1/4"]), ("rpm", [4500, 5000, 5200])],
            },
            {
                "name": "{brand} Cordless Jigsaw",
                "desc": "Variable-speed jigsaw for curves and angles. Tool-free blade change, orbital action setting. Cuts wood, metal, and plastic.",
                "price_range": (59, 199),
                "specs": lambda: {"strokes_per_min": f"{random.randint(500,3100)}", "stroke_length": "1 inch", "bevel_cut": "0-45 degrees", "blade_system": "T-shank"},
                "vars": [],
            },
            {
                "name": "{brand} {v}V Random Orbit Sander",
                "desc": "Cordless 5-inch random orbit sander. Variable speed, dust bag included. Ideal for wood finishing.",
                "price_range": (49, 149),
                "specs": lambda v: {"voltage": f"{v}V", "pad_size": "5 inch", "orbits_per_min": f"{random.randint(8000,12000)}", "variable_speed": "Yes"},
                "vars": [("v", [12, 18, 20])],
            },
            {
                "name": "{brand} Cordless Reciprocating Saw",
                "desc": "Demolition-ready reciprocating saw. Variable speed trigger, pivoting shoe. Cuts through wood, metal, and pipe.",
                "price_range": (79, 279),
                "specs": lambda: {"strokes_per_min": f"{random.randint(0,3000)}", "stroke_length": "1-1/8 inch", "weight": f"{random.uniform(5.5,7.5):.1f} lbs", "tool_free_blade": "Yes"},
                "vars": [],
            },
            {
                "name": "{brand} Cordless Oscillating Multi-Tool",
                "desc": "Versatile multi-tool for cutting, sanding, and scraping. Tool-free accessory change. Works with most accessory brands.",
                "price_range": (69, 199),
                "specs": lambda: {"oscillations_per_min": f"{random.randint(10000,20000)}", "oscillation_angle": "3.2 degrees", "accessory_interface": "Universal"},
                "vars": [],
            },
            {
                "name": "{brand} Cordless Nailer - 18-Gauge Brad",
                "desc": "Cordless 18-gauge brad nailer. Dry-fire lockout, sequential and bump fire modes. No compressor needed.",
                "price_range": (149, 349),
                "specs": lambda: {"gauge": "18", "nail_length": "5/8 to 2-1/8 inch", "magazine_capacity": "110 nails", "actuation_modes": "Sequential / Bump"},
                "vars": [],
            },
            {
                "name": "{brand} Benchtop Drill Press - {s}-Inch",
                "desc": "5-speed benchtop drill press with work light. Adjustable table, depth stop, fence included.",
                "price_range": (129, 399),
                "specs": lambda s: {"swing": f"{s} inch", "speeds": "5", "chuck_size": "1/2 inch", "table_size": "6-1/2 x 6-1/2 inch", "motor": "1/2 HP"},
                "vars": [("s", [10, 12])],
            },
            {
                "name": "{brand} {a}-Amp Angle Grinder - {s}-Inch",
                "desc": "Corded angle grinder with no-lock paddle switch and side handle. Ideal for grinding, cutting, and polishing.",
                "price_range": (39, 149),
                "specs": lambda a, s: {"amps": f"{a}A", "disc_size": f"{s} inch", "rpm": f"{random.randint(10000,12000)}", "spindle_thread": "5/8-11"},
                "vars": [("a", [6, 7, 9, 11]), ("s", ["4-1/2", "5", "7"])],
            },
        ],
    },
    "Hand Tools": {
        "brands": ["Stanley", "Irwin", "Klein Tools", "Channellock", "Wera", "Estwing", "Craftsman", "Knipex"],
        "products": [
            {
                "name": "{brand} {p}-Piece Combination Wrench Set - SAE",
                "desc": "Chrome vanadium steel wrenches with mirror polish finish. 12-point box end for better engagement.",
                "price_range": (19, 89),
                "specs": lambda p: {"piece_count": str(p), "material": "Chrome Vanadium Steel", "finish": "Mirror Polish", "sizes": "SAE 1/4\" - 1-1/4\""},
                "vars": [("p", [8, 10, 12, 14])],
            },
            {
                "name": "{brand} Claw Hammer - {w} oz",
                "desc": "Smooth-face claw hammer with vibration-dampening grip. Drop-forged head, curved claw for nail pulling.",
                "price_range": (14, 49),
                "specs": lambda w: {"weight": f"{w} oz", "handle": "Fiberglass / Hickory", "head": "Drop-Forged Steel", "face": "Smooth"},
                "vars": [("w", [16, 20, 22])],
            },
            {
                "name": "{brand} 25-Foot Tape Measure",
                "desc": "Auto-lock tape measure with standout up to 11 ft. High-visibility blade with dual-sided print.",
                "price_range": (9, 39),
                "specs": lambda: {"length": "25 ft", "blade_width": "1-1/4 inch", "standout": "11 ft", "locking": "Auto-Lock"},
                "vars": [],
            },
            {
                "name": "{brand} {p}-Piece Screwdriver Set",
                "desc": "Magnetic tip screwdrivers with comfort-grip handles. Includes Phillips and flat-head in various sizes.",
                "price_range": (12, 49),
                "specs": lambda p: {"piece_count": str(p), "tip_types": "Phillips, Flathead, Torx", "handle": "Tri-lobular"},
                "vars": [("p", [6, 8, 10, 12])],
            },
            {
                "name": "{brand} Utility Knife",
                "desc": "Retractable utility knife with quick-change blade system. Includes 5 spare blades. Metal body construction.",
                "price_range": (8, 29),
                "specs": lambda: {"blade_type": "Standard 18mm", "body": "Metal", "spare_blades": "5", "blade_change": "Tool-Free"},
                "vars": [],
            },
            {
                "name": "{brand} Level - {l}-Inch",
                "desc": "Box beam aluminum level with 3 acrylic vials. Accuracy ±0.5mm/m. Magnetic edge for hands-free use.",
                "price_range": (15, 79),
                "specs": lambda l: {"length": f"{l} inch", "accuracy": "±0.5mm/m", "material": "Box Beam Aluminum", "vials": "3"},
                "vars": [("l", [24, 48, 72, 96])],
            },
            {
                "name": "{brand} Needle-Nose Pliers - {l}-Inch",
                "desc": "High-leverage needle-nose pliers. Joint is forged, not stamped. Induction-hardened cutting edge.",
                "price_range": (11, 39),
                "specs": lambda l: {"length": f"{l} inch", "jaw_type": "Long Nose", "cutting": "Induction Hardened"},
                "vars": [("l", [6, 8])],
            },
            {
                "name": "{brand} Pipe Wrench - {s}-Inch",
                "desc": "Drop-forged pipe wrench with heel jaw. I-beam handle design. Self-cleaning nut for easy adjustment.",
                "price_range": (19, 69),
                "specs": lambda s: {"size": f"{s} inch", "capacity": f"Up to {s//2} inch pipe", "material": "Forged Steel"},
                "vars": [("s", [10, 12, 14, 18])],
            },
        ],
    },
    "Electrical": {
        "brands": ["Leviton", "Lutron", "Square D", "Eaton", "Hubbell", "Legrand", "GE", "Pass & Seymour"],
        "products": [
            {
                "name": "{brand} Smart Dimmer Switch - WiFi",
                "desc": "In-wall smart dimmer with no-neutral option. Works with LED, CFL, and incandescent bulbs. App control and scheduling.",
                "price_range": (29, 79),
                "specs": lambda: {"voltage": "120V", "max_load": "600W LED / 1000W Incandescent", "connectivity": "WiFi 2.4GHz", "neutral_required": "No"},
                "vars": [],
            },
            {
                "name": "{brand} GFCI Outlet - 20A Tamper Resistant",
                "desc": "20A GFCI outlet with tamper-resistant shutters. Self-testing, LED indicator. UL Listed. White.",
                "price_range": (14, 34),
                "specs": lambda: {"amperage": "20A", "voltage": "125V", "tamper_resistant": "Yes", "self_testing": "Yes", "color": "White"},
                "vars": [],
            },
            {
                "name": "{brand} {a}A {s}-Space Load Center",
                "desc": "{s}-space indoor load center with {a}A main breaker. Copper bus bar, combination knockouts. CSA Listed.",
                "price_range": (89, 349),
                "specs": lambda a, s: {"amperage": f"{a}A", "spaces": str(s), "circuits": str(s * 2), "bus": "Copper", "main_breaker": "Included"},
                "vars": [("a", [100, 150, 200]), ("s", [20, 30, 40])],
            },
            {
                "name": "{brand} LED Shop Light - {w}W {l}-Inch",
                "desc": "Linkable LED shop light with pull chain. Plug-in or hardwire. Daylight 5000K, {lm} lumens.",
                "price_range": (24, 89),
                "specs": lambda w, l, lm: {"wattage": f"{w}W", "length": f"{l} inch", "lumens": str(lm), "color_temp": "5000K Daylight", "cri": "80+"},
                "vars": [("w", [40, 55, 65, 80]), ("l", [24, 48]), ("lm", [4000, 5000, 6500, 8000])],
            },
            {
                "name": "{brand} Arc Fault Circuit Breaker - {a}A",
                "desc": "Combination AFCI breaker protects against arc faults. Required by NEC for bedroom circuits. Plug-on neutral.",
                "price_range": (29, 59),
                "specs": lambda a: {"amperage": f"{a}A", "type": "Combination AFCI", "voltage": "120V", "pole": "Single", "interrupt_rating": "10,000A"},
                "vars": [("a", [15, 20])],
            },
            {
                "name": "{brand} Smart Plug with Energy Monitoring",
                "desc": "WiFi smart plug tracks real-time energy usage. Works with Alexa and Google Home. Compact design fits side-by-side.",
                "price_range": (19, 39),
                "specs": lambda: {"voltage": "120V", "amperage": "15A", "max_load": "1800W", "connectivity": "WiFi 2.4GHz", "energy_monitoring": "Yes"},
                "vars": [],
            },
            {
                "name": "{brand} {w}W LED Flood Light Bulb - {p}Pack",
                "desc": "BR30 LED flood light bulbs. {w}W replaces {eq}W incandescent. Dimmable, 2700K warm white.",
                "price_range": (9, 39),
                "specs": lambda w, p, eq: {"wattage": f"{w}W", "pack": str(p), "equivalent": f"{eq}W", "lumens": f"{w * 75}", "color_temp": "2700K", "dimmable": "Yes"},
                "vars": [("w", [8, 10, 13, 15]), ("p", [2, 4, 6]), ("eq", [60, 75, 100])],
            },
            {
                "name": "{brand} Outdoor Motion Security Light - {w}W",
                "desc": "Dual-head motion-activated floodlight. Adjustable heads, 180° detection angle, 30-ft range. Dusk-to-dawn sensor.",
                "price_range": (29, 99),
                "specs": lambda w: {"wattage": f"{w}W", "lumens": str(w * 80), "detection_range": "30 ft", "detection_angle": "180 degrees", "sensor": "Dusk-to-Dawn + Motion"},
                "vars": [("w", [20, 30, 45, 50])],
            },
        ],
    },
    "Plumbing": {
        "brands": ["Moen", "Delta", "Kohler", "American Standard", "Pfister", "Gerber", "Watts", "SharkBite"],
        "products": [
            {
                "name": "{brand} Single-Handle Kitchen Faucet - Pull-Down",
                "desc": "Pull-down kitchen faucet with 3-function spray head: stream, spray, pause. Spot-resist stainless finish.",
                "price_range": (99, 399),
                "specs": lambda: {"handle": "Single", "type": "Pull-Down", "finish": random.choice(["Chrome", "Brushed Nickel", "Matte Black", "Stainless"]), "spray_functions": "3", "deck_holes": "1"},
                "vars": [],
            },
            {
                "name": "{brand} Bathroom Faucet - {h} Handle",
                "desc": "Bathroom sink faucet with water-saving aerator (1.2 GPM). Includes pop-up drain assembly.",
                "price_range": (49, 249),
                "specs": lambda h: {"handles": str(h), "flow_rate": "1.2 GPM", "finish": random.choice(["Chrome", "Brushed Nickel", "Oil Rubbed Bronze"]), "drain": "Pop-Up Included"},
                "vars": [("h", [1, 2])],
            },
            {
                "name": "{brand} {g}-Gallon Water Heater - Electric",
                "desc": "Electric water heater with dual heating elements. 10-year tank warranty, 2-year parts warranty. Energy Star certified.",
                "price_range": (349, 899),
                "specs": lambda g: {"capacity": f"{g} gallons", "element": "Dual 4500W", "recovery_rate": f"{g // 6} GPH @ 90°F rise", "warranty_tank": "10 years", "energy_factor": "0.93"},
                "vars": [("g", [30, 40, 50, 60, 80])],
            },
            {
                "name": "{brand} SharkBite Push-to-Connect Fitting - {s}-Inch {t}",
                "desc": "Push-to-connect plumbing fitting for copper, PEX, CPVC, and PE-RT pipe. No soldering or tools required.",
                "price_range": (4, 19),
                "specs": lambda s, t: {"size": f"{s} inch", "type": t, "compatible_pipe": "Copper, PEX, CPVC, PE-RT", "tool_required": "No", "max_pressure": "200 PSI"},
                "vars": [("s", ["1/2", "3/4", "1"]), ("t", ["Coupling", "Elbow", "Tee", "Cap"])],
            },
            {
                "name": "{brand} Toilet - Elongated {f} Flush",
                "desc": "WaterSense certified toilet uses {gal} GPF. Includes seat. ADA compliant comfort height (16.5\").",
                "price_range": (149, 499),
                "specs": lambda f, gal: {"flush_type": f, "gpf": str(gal), "bowl": "Elongated", "height": "16.5 inch (ADA)", "seat_included": "Yes"},
                "vars": [("f", ["1.28 GPF", "1.0 GPF Dual Flush"]), ("gal", [1.28, 1.0])],
            },
            {
                "name": "{brand} Sump Pump - {hp} HP",
                "desc": "Submersible sump pump with cast iron switch housing. Handles up to {gph} GPH. 10-ft power cord.",
                "price_range": (99, 349),
                "specs": lambda hp, gph: {"horsepower": f"{hp} HP", "max_flow": f"{gph} GPH", "max_head": "25 ft", "discharge": "1-1/2 inch NPT", "power_cord": "10 ft"},
                "vars": [("hp", ["1/3", "1/2", "3/4", "1"]), ("gph", [1800, 2400, 3000, 4200])],
            },
            {
                "name": "{brand} Garbage Disposal - {hp} HP",
                "desc": "Stainless steel grinding components. Sound insulation, auto-reverse jam clearing. Power cord included.",
                "price_range": (79, 259),
                "specs": lambda hp: {"motor": f"{hp} HP", "grinding": "Stainless Steel", "feed_type": "Continuous", "cord_included": "Yes", "sound_insulation": "Yes"},
                "vars": [("hp", ["1/2", "3/4", "1"])],
            },
            {
                "name": "{brand} PEX Pipe - {s}-Inch x {l}-Ft",
                "desc": "Flexible cross-linked polyethylene pipe for hot and cold water supply. Color-coded: red=hot, blue=cold.",
                "price_range": (12, 149),
                "specs": lambda s, l: {"diameter": f"{s} inch", "length": f"{l} ft", "material": "PEX-A", "max_temp": "200°F", "max_pressure": "100 PSI at 180°F"},
                "vars": [("s", ["1/2", "3/4", "1"]), ("l", [25, 50, 100])],
            },
        ],
    },
    "Building Materials": {
        "brands": ["Owens Corning", "James Hardie", "USG", "Georgia-Pacific", "LP Building Products", "Quikrete", "Simpson Strong-Tie", "GRK Fasteners"],
        "products": [
            {
                "name": "{brand} R-{r} Insulation Batts - {w}-Inch Wide",
                "desc": "Faced fiberglass insulation batts. Fits standard {w2}\" wall framing. Vapor retarder facing. Per bag ({sqft} sq ft).",
                "price_range": (19, 79),
                "specs": lambda r, w, w2, sqft: {"r_value": f"R-{r}", "width": f"{w} inch", "thickness": f"{r//4} inch", "coverage": f"{sqft} sq ft/bag", "facing": "Kraft Paper"},
                "vars": [("r", [13, 15, 19, 21, 30, 38]), ("w", [15, 23]), ("w2", [2, 6]), ("sqft", [40, 48, 88])],
            },
            {
                "name": "{brand} {t} Drywall - {w}x{l} Sheet",
                "desc": "{t} drywall panel for interior walls and ceilings. {th}-inch thick. Fire-resistant core.",
                "price_range": (9, 39),
                "specs": lambda t, w, l, th: {"type": t, "width": f"{w} ft", "length": f"{l} ft", "thickness": f"{th} inch", "weight": f"{w * l * 2.2:.0f} lbs"},
                "vars": [("t", ["Regular", "Moisture Resistant", "Fire Resistant (Type X)"]), ("w", [4]), ("l", [8, 10, 12]), ("th", ["1/2", "5/8"])],
            },
            {
                "name": "{brand} Fiber Cement Siding - Lap",
                "desc": "Pre-primed fiber cement lap siding. Resists rot, fire, and insects. 30-year limited warranty. Per plank.",
                "price_range": (3, 12),
                "specs": lambda: {"material": "Fiber Cement", "width": f"{random.choice([6,7,8,9,12])} inch exposure", "length": "12 ft", "primed": "Yes", "warranty": "30 years"},
                "vars": [],
            },
            {
                "name": "{brand} Concrete Mix - {w}-lb Bag",
                "desc": "General purpose concrete mix. Just add water. 4,000 PSI compressive strength at 28 days. For footings, slabs, and walls.",
                "price_range": (5, 29),
                "specs": lambda w: {"weight": f"{w} lbs", "compressive_strength": "4000 PSI @ 28 days", "set_time": "15-30 min", "yield": f"{w * 0.012:.2f} cu ft"},
                "vars": [("w", [50, 60, 80])],
            },
            {
                "name": "{brand} OSB Sheathing - {t}-Inch {w}x{l}",
                "desc": "Oriented strand board sheathing for roof, wall, and floor applications. Moisture-resistant edge seal.",
                "price_range": (19, 59),
                "specs": lambda t, w, l: {"thickness": f"{t} inch", "size": f"{w}x{l} ft", "span_rating": "24/16", "edge_seal": "Yes", "exposure": "Exposure 1"},
                "vars": [("t", ["7/16", "15/32", "23/32"]), ("w", [4]), ("l", [8])],
            },
            {
                "name": "{brand} Structural Connector - Joist Hanger {s}",
                "desc": "ZMAX galvanized joist hanger for lumber-to-lumber connections. Code listed. Load tested.",
                "price_range": (1, 12),
                "specs": lambda s: {"size": s, "material": "18-Gauge Galvanized Steel", "finish": "ZMAX", "loads": "Load Tested to 2,100 lbs"},
                "vars": [("s", ["2x6", "2x8", "2x10", "2x12", "3x8", "3x10", "4x10", "4x12"])],
            },
            {
                "name": "{brand} Deck Screw - #{g} x {l} ({p}-Pack)",
                "desc": "Exterior deck screws with star drive recess. Coated for corrosion resistance. Self-tapping, no pre-drill needed in softwoods.",
                "price_range": (8, 39),
                "specs": lambda g, l, p: {"gauge": f"#{g}", "length": f"{l} inch", "pack": str(p), "drive": "Star/Torx", "coating": "ACQ Compatible", "material": "Carbon Steel"},
                "vars": [("g", [8, 9, 10]), ("l", ["1-5/8", "2", "2-1/2", "3", "3-1/2"]), ("p", [1, 5, 25])],
            },
            {
                "name": "{brand} Vapor Barrier - {w}-Ft x {l}-Ft x {th}-Mil",
                "desc": "Polyethylene vapor barrier for crawl spaces and under-slab use. Cross-laminated for tear resistance.",
                "price_range": (29, 149),
                "specs": lambda w, l, th: {"width": f"{w} ft", "length": f"{l} ft", "thickness": f"{th} mil", "coverage": f"{w * l} sq ft", "material": "Polyethylene"},
                "vars": [("w", [10, 12, 16, 20]), ("l", [25, 50, 100]), ("th", [6, 10, 12, 20])],
            },
        ],
    },
    "Paint & Supplies": {
        "brands": ["Behr", "Sherwin-Williams", "Benjamin Moore", "Valspar", "Rust-Oleum", "Zinsser", "Purdy", "Wooster"],
        "products": [
            {
                "name": "{brand} Interior Paint & Primer - {f} Finish - {s}",
                "desc": "One-coat coverage interior paint and primer. Low-VOC formula, mildew resistant. Washable when dry.",
                "price_range": (29, 79),
                "specs": lambda f, s: {"finish": f, "size": s, "coverage": "250-400 sq ft/gal", "dry_time": "1 hour", "voc": "Low-VOC (<50 g/L)", "coats": "1"},
                "vars": [("f", ["Flat", "Eggshell", "Satin", "Semi-Gloss", "Gloss"]), ("s", ["1 Gallon", "5 Gallon"])],
            },
            {
                "name": "{brand} Exterior Paint - {f} - {s}",
                "desc": "100% acrylic exterior paint. Fade resistant, flexible film resists cracking and peeling. 25-year warranty.",
                "price_range": (39, 99),
                "specs": lambda f, s: {"finish": f, "size": s, "coverage": "250-400 sq ft/gal", "recoat_time": "4 hours", "full_cure": "30 days", "warranty": "25 years"},
                "vars": [("f", ["Flat", "Satin", "Semi-Gloss"]), ("s", ["1 Gallon", "5 Gallon"])],
            },
            {
                "name": "{brand} {c}-Inch Angle Sash Paint Brush",
                "desc": "Professional angle sash brush for trim and cutting in. {m} bristles hold more paint. Stainless ferrule.",
                "price_range": (8, 29),
                "specs": lambda c, m: {"width": f"{c} inch", "bristles": m, "angle": "Angled Sash", "ferrule": "Stainless Steel"},
                "vars": [("c", [1, 1.5, 2, 2.5, 3]), ("m", ["Nylon/Polyester", "100% Polyester", "Natural Bristle"])],
            },
            {
                "name": "{brand} {s}-Inch Roller Cover - {n} Nap",
                "desc": "Roller cover for smooth to semi-smooth surfaces. {m} material. Fits standard 1/2-inch roller frames.",
                "price_range": (4, 19),
                "specs": lambda s, n, m: {"size": f"{s} inch", "nap": n, "material": m, "surface": "Smooth to Semi-Smooth"},
                "vars": [("s", [9, 18]), ("n", ["1/4 inch", "3/8 inch", "1/2 inch", "3/4 inch"]), ("m", ["Polyester", "Microfiber", "Wool"])],
            },
            {
                "name": "{brand} Primer - {t} - {s}",
                "desc": "{t} primer for better paint adhesion. Seals stains, blocks odors. Interior/exterior use.",
                "price_range": (19, 59),
                "specs": lambda t, s: {"type": t, "size": s, "dry_time": "1 hour", "coverage": "300-400 sq ft/gal", "finish": "Flat"},
                "vars": [("t", ["All-Purpose", "Stain-Blocking", "Shellac-Based", "High-Hide White"]), ("s", ["1 Quart", "1 Gallon", "5 Gallon"])],
            },
            {
                "name": "{brand} Spray Paint - {c} - {f}",
                "desc": "All-purpose spray paint with comfort spray tip. Dries in 20 minutes, covers up to 12 sq ft. Any-angle spray.",
                "price_range": (5, 14),
                "specs": lambda c, f: {"color": c, "finish": f, "coverage": "12 sq ft", "dry_time": "20 min", "size": "12 oz", "any_angle": "Yes"},
                "vars": [("c", ["Flat Black", "Gloss White", "Hunter Green", "Gloss Red", "Chrome", "Hammered Copper", "Satin Nickel"]), ("f", ["Flat", "Gloss", "Satin", "Hammered"])],
            },
            {
                "name": "{brand} Caulk - {t} - {s}",
                "desc": "{t} caulk, flexible and paintable. 50-year durability. Seals gaps up to 1 inch. Soap-and-water cleanup.",
                "price_range": (4, 14),
                "specs": lambda t, s: {"type": t, "size": s, "flexibility": "35% elongation", "paintable": "Yes", "waterproof": "Yes"},
                "vars": [("t", ["Acrylic Latex", "Silicone", "Paintable Silicone", "Sanded"]), ("s", ["10.1 oz", "5.5 oz"])],
            },
        ],
    },
    "Flooring": {
        "brands": ["Pergo", "Armstrong", "Shaw", "Mohawk", "TrafficMaster", "LifeProof", "COREtec", "Quick-Step"],
        "products": [
            {
                "name": "{brand} {t} Flooring - {color} - {sqft} sq ft/case",
                "desc": "{t} flooring with {mm}mm wear layer. Click-lock glueless installation. Waterproof core. Attached underlayment.",
                "price_range": (39, 149),
                "specs": lambda t, color, sqft, mm: {"type": t, "color": color, "coverage": f"{sqft} sq ft/case", "wear_layer": f"{mm}mm", "waterproof": "Yes", "underlayment": "Attached"},
                "vars": [("t", ["Luxury Vinyl Plank", "Laminate", "Engineered Hardwood"]), ("color", ["Barnwood Gray", "Golden Oak", "Driftwood", "Espresso", "Natural Maple", "Rustic Hickory"]), ("sqft", [16, 20, 23]), ("mm", [12, 20, 28])],
            },
            {
                "name": "{brand} Hardwood Flooring - {species} - {w}-Inch",
                "desc": "Solid {species} hardwood flooring. Prefinished with UV-cured aluminum oxide. Sand and refinish up to 4 times.",
                "price_range": (3, 12),
                "specs": lambda species, w: {"species": species, "width": f"{w} inch", "thickness": "3/4 inch solid", "finish": "Prefinished", "refinishable": "Yes (4+ times)"},
                "vars": [("species", ["Red Oak", "White Oak", "Maple", "Hickory", "Cherry", "Walnut"]), ("w", [3, 4, 5, 6])],
            },
            {
                "name": "{brand} Porcelain Tile - {s}x{s} - {b} (per sq ft)",
                "desc": "Through-body porcelain tile. Frost resistant, PEI 4 wear rating for heavy residential and light commercial use.",
                "price_range": (1, 7),
                "specs": lambda s, b: {"size": f"{s}x{s} inch", "material": "Porcelain", "finish": b, "pei_rating": "4", "frost_resistant": "Yes"},
                "vars": [("s", [12, 16, 18, 24]), ("b", ["Matte", "Polished", "Honed", "Structured"])],
            },
            {
                "name": "{brand} Carpet - {s} - Per Sq Yd",
                "desc": "{pile} pile carpet. Stain-protected fibers. 15-year stain and soil warranty. Includes 5-year wear warranty.",
                "price_range": (8, 39),
                "specs": lambda s, pile: {"style": s, "pile_type": pile, "fiber": "Nylon / Polyester", "stain_protection": "Yes", "warranty_wear": "5 years"},
                "vars": [("s", ["Berber Loop", "Frieze Twist", "Plush Cut Pile", "Patterned"]), ("pile", ["Loop", "Frieze", "Cut Pile"])],
            },
            {
                "name": "{brand} Carpet Padding - {t} - {th}-Inch",
                "desc": "{t} carpet padding. Moisture barrier, antimicrobial treatment. High-density for durability.",
                "price_range": (19, 59),
                "specs": lambda t, th: {"type": t, "thickness": f"{th} inch", "density": "8 lbs/cu ft", "moisture_barrier": "Yes", "antimicrobial": "Yes"},
                "vars": [("t", ["Rebond Foam", "Memory Foam", "Fiber"]), ("th", ["3/8", "7/16", "1/2"])],
            },
            {
                "name": "{brand} Tile Underlayment - {s}x{s}-Ft Sheet",
                "desc": "Uncoupling membrane for tile installation. Prevents cracking over problematic substrates. Waterproofing when seams taped.",
                "price_range": (29, 199),
                "specs": lambda s: {"size": f"{s}x{s} ft", "material": "HDPE", "thickness": "1/8 inch", "tile_max_size": "Any", "waterproof": "With Seam Tape"},
                "vars": [("s", [5, 10, 20])],
            },
        ],
    },
    "Outdoor & Garden": {
        "brands": ["Greenworks", "EGO", "Husqvarna", "Toro", "Ryobi", "Craftsman", "Sun Joe", "BLACK+DECKER"],
        "products": [
            {
                "name": "{brand} {v}V Cordless Lawn Mower - {d}-Inch",
                "desc": "Self-propelled cordless mower with {d}-inch steel deck. 6 cutting heights (1.5\"-4\"). Battery and charger included.",
                "price_range": (249, 749),
                "specs": lambda v, d: {"voltage": f"{v}V", "deck": f"{d} inch Steel", "self_propelled": "Yes", "cutting_heights": "6 (1.5-4 inch)", "bag_capacity": "1.9 bushels", "mulch_bag_side_discharge": "3-in-1"},
                "vars": [("v", [40, 56, 80]), ("d", [19, 20, 21])],
            },
            {
                "name": "{brand} Cordless String Trimmer",
                "desc": "Bump-feed string trimmer with auto-sensing motor. 13-inch cutting swath. Telescoping shaft, edge guide.",
                "price_range": (79, 249),
                "specs": lambda: {"cutting_swath": "13 inch", "line_diameter": "0.065 inch", "feed_type": "Bump Feed", "shaft": "Straight", "weight": f"{random.uniform(5.5,8.5):.1f} lbs"},
                "vars": [],
            },
            {
                "name": "{brand} Gas Pressure Washer - {psi} PSI",
                "desc": "{psi} PSI, {gpm} GPM pressure washer. {cc}cc OHV engine. Includes 5 quick-connect nozzles and 25-ft hose.",
                "price_range": (299, 699),
                "specs": lambda psi, gpm, cc: {"psi": str(psi), "gpm": str(gpm), "engine": f"{cc}cc OHV", "nozzles": "5 Quick-Connect", "hose": "25 ft"},
                "vars": [("psi", [2800, 3100, 3200, 3400]), ("gpm", [2.3, 2.5, 2.8]), ("cc", [160, 163, 196, 212])],
            },
            {
                "name": "{brand} Electric Pressure Washer - {psi} PSI",
                "desc": "{psi} PSI electric pressure washer. {amp}A motor. Total Stop System saves energy. Includes 20-ft hose.",
                "price_range": (99, 299),
                "specs": lambda psi, amp: {"psi": str(psi), "gpm": "1.2", "motor": f"{amp}A Electric", "tss": "Yes (Total Stop System)", "hose": "20 ft"},
                "vars": [("psi", [1600, 1800, 2030, 2300]), ("amp", [11, 13, 14.5])],
            },
            {
                "name": "{brand} Cordless Leaf Blower - {v}V",
                "desc": "Cordless leaf blower with variable speed. {mph} MPH / {cfm} CFM. Turbo boost button. Rubber tip nozzle.",
                "price_range": (69, 249),
                "specs": lambda v, mph, cfm: {"voltage": f"{v}V", "max_mph": f"{mph} MPH", "max_cfm": f"{cfm} CFM", "variable_speed": "Yes", "turbo_boost": "Yes"},
                "vars": [("v", [20, 40, 56]), ("mph", [90, 120, 150, 180]), ("cfm", [400, 500, 650, 730])],
            },
            {
                "name": "{brand} Raised Garden Bed - {w}x{l}x{h} Inches",
                "desc": "Cedar raised garden bed with no-rot construction. Pre-cut boards, easy assembly, no tools required.",
                "price_range": (49, 199),
                "specs": lambda w, l, h: {"width": f"{w} inch", "length": f"{l} inch", "height": f"{h} inch", "material": "Cedar", "capacity": f"{w * l * h / 1728:.1f} cu ft"},
                "vars": [("w", [24, 36, 48]), ("l", [48, 72, 96]), ("h", [8, 10, 12])],
            },
            {
                "name": "{brand} Garden Hose - {l}-Ft x {d}-Inch",
                "desc": "Kink-resistant garden hose with solid brass fittings. {layer}-layer reinforced for high pressure. Drinking water safe.",
                "price_range": (19, 79),
                "specs": lambda l, d, layer: {"length": f"{l} ft", "diameter": f"{d} inch", "layers": str(layer), "max_psi": "150 PSI", "material": "Rubber / Vinyl Hybrid"},
                "vars": [("l", [25, 50, 75, 100]), ("d", ["5/8", "3/4"]), ("layer", [4, 5, 6])],
            },
            {
                "name": "{brand} Patio Umbrella - {d}-Inch - {color}",
                "desc": "Market patio umbrella with push-button tilt. UV-resistant fabric. Steel pole with powder coat finish.",
                "price_range": (49, 199),
                "specs": lambda d, color: {"diameter": f"{d} inch", "color": color, "tilt": "Push-Button", "uv_protection": "UPF 50+", "pole": "Steel 1.5 inch"},
                "vars": [("d", [9, 10, 11]), ("color", ["Navy Blue", "Beige", "Forest Green", "Terracotta", "Gray", "Red"])],
            },
        ],
    },
    "Storage & Organization": {
        "brands": ["Rubbermaid", "Gladiator", "Husky", "Seville Classics", "Akro-Mils", "Stack-On", "NewAge", "Prepac"],
        "products": [
            {
                "name": "{brand} {s}-Piece Garage Storage System",
                "desc": "Wall-mounted steel garage storage system. {lbs}-lb load capacity per shelf. Powder-coated finish, easy assembly.",
                "price_range": (149, 799),
                "specs": lambda s, lbs: {"pieces": str(s), "load_per_shelf": f"{lbs} lbs", "material": "Steel", "finish": "Powder Coat", "wall_mount": "Yes"},
                "vars": [("s", [3, 4, 5, 8, 12]), ("lbs", [100, 200, 350, 500])],
            },
            {
                "name": "{brand} {d}-Drawer Tool Chest",
                "desc": "Ball-bearing drawer slides, 100-lb capacity per drawer. Keyed lock. Bottom casters for mobility.",
                "price_range": (99, 799),
                "specs": lambda d: {"drawers": str(d), "load_per_drawer": "100 lbs", "slides": "Ball Bearing", "lock": "Keyed", "casters": "Yes"},
                "vars": [("d", [4, 5, 6, 8, 10])],
            },
            {
                "name": "{brand} {g}-Gallon Storage Tote - {p}-Pack",
                "desc": "Stackable storage tote with secure lid. Snap-tight latches. Weather-resistant. Ideal for garage or attic.",
                "price_range": (9, 59),
                "specs": lambda g, p: {"capacity": f"{g} gallons", "pack": str(p), "stackable": "Yes", "weather_resistant": "Yes", "color": "Gray/Yellow"},
                "vars": [("g", [18, 27, 30, 66]), ("p", [1, 2, 4, 6])],
            },
            {
                "name": "{brand} Wire Shelving Unit - {w}x{d}x{h} Inches",
                "desc": "Chrome wire shelving unit with adjustable shelves. {s} shelves, {lbs}-lb capacity each. Stackable and expandable.",
                "price_range": (39, 149),
                "specs": lambda w, d, h, s, lbs: {"width": f"{w} inch", "depth": f"{d} inch", "height": f"{h} inch", "shelves": str(s), "capacity_per_shelf": f"{lbs} lbs"},
                "vars": [("w", [24, 36, 48]), ("d", [14, 18, 24]), ("h", [48, 60, 72]), ("s", [4, 5, 6]), ("lbs", [200, 350, 500])],
            },
            {
                "name": "{brand} Pegboard Kit - {w}x{l} Inches",
                "desc": "Pegboard organizer kit with 50+ hooks and accessories. Metal pegboard with backer panel. Includes mounting hardware.",
                "price_range": (29, 99),
                "specs": lambda w, l: {"width": f"{w} inch", "height": f"{l} inch", "hooks": "50+", "material": "Metal", "color": "Black"},
                "vars": [("w", [24, 36, 48]), ("l", [24, 36, 48])],
            },
        ],
    },
    "Safety & Security": {
        "brands": ["Kidde", "First Alert", "Ring", "Schlage", "Kwikset", "Master Lock", "Honeywell", "ADT"],
        "products": [
            {
                "name": "{brand} Smoke & CO Detector - {p}",
                "desc": "Combination smoke and carbon monoxide detector. {p}. 10-year sealed battery. Interconnectable via RF.",
                "price_range": (19, 79),
                "specs": lambda p: {"type": "Combination Smoke + CO", "power": p, "battery_life": "10 years", "interconnectable": "Yes (RF Wireless)", "alarm": "85 dB"},
                "vars": [("p", ["Battery Operated", "Hardwired with Battery Backup", "Plug-In"])],
            },
            {
                "name": "{brand} Fire Extinguisher - {s}-lb {t}",
                "desc": "{t} fire extinguisher. Rechargeable with metal valve. Includes mounting bracket and instruction label.",
                "price_range": (29, 119),
                "specs": lambda s, t: {"weight": f"{s} lbs", "type": t, "rating": "2-A:10-B:C", "rechargeable": "Yes", "discharge_time": "14 seconds"},
                "vars": [("s", [2.5, 5, 10]), ("t", ["ABC Dry Chemical", "Clean Agent", "CO2"])],
            },
            {
                "name": "{brand} Smart Lock - Keypad + {c}",
                "desc": "Keypad smart lock with auto-lock and tamper alarm. Works with Alexa and Google Assistant. 100 access codes.",
                "price_range": (99, 299),
                "specs": lambda c: {"connectivity": c, "codes": "100", "auto_lock": "Yes", "tamper_alarm": "Yes", "batteries": "4 AA"},
                "vars": [("c", ["WiFi", "Bluetooth", "Zigbee", "Z-Wave"])],
            },
            {
                "name": "{brand} Security Camera - {r} - {c}",
                "desc": "Wired security camera with {r} resolution. Night vision, motion alerts. Weatherproof IP67. {c} video storage.",
                "price_range": (49, 299),
                "specs": lambda r, c: {"resolution": r, "night_vision": "Color Night Vision", "motion_detection": "AI Person Detection", "weatherproof": "IP67", "storage": c},
                "vars": [("r", ["1080p", "2K", "4K"]), ("c", ["16GB Local", "Cloud Subscription", "NVR/DVR"])],
            },
            {
                "name": "{brand} Padlock - {s}-Inch Shackle",
                "desc": "Hardened steel shackle with 4-pin cylinder. Dual ball-locking mechanism. Boron carbide shackle for cut resistance.",
                "price_range": (9, 49),
                "specs": lambda s: {"shackle": f"{s} inch", "material": "Hardened Steel", "pins": "4-pin cylinder", "locking": "Dual Ball"},
                "vars": [("s", ["3/4", "1", "1-1/2"])],
            },
        ],
    },
    "Heating & Cooling": {
        "brands": ["Honeywell", "Ecobee", "Nest", "Carrier", "Daikin", "LG", "Mitsubishi", "Friedrich"],
        "products": [
            {
                "name": "{brand} Smart Thermostat with Voice Control",
                "desc": "Smart thermostat with built-in Alexa and remote sensor. Geofencing, scheduling, energy reports. Works with all HVAC systems.",
                "price_range": (79, 249),
                "specs": lambda: {"compatibility": "All HVAC Systems", "connectivity": "WiFi + Bluetooth", "remote_sensors": "Yes", "geofencing": "Yes", "display": "Color Touchscreen"},
                "vars": [],
            },
            {
                "name": "{brand} {btu}BTU Window Air Conditioner",
                "desc": "Energy Star window AC cools up to {sqft} sq ft. {fan} fan speeds, dehumidifier mode, sleep mode. Remote control included.",
                "price_range": (149, 599),
                "specs": lambda btu, sqft, fan: {"btu": f"{btu:,}", "coverage": f"{sqft} sq ft", "fan_speeds": str(fan), "energy_star": "Yes", "dehumidifier": "Yes"},
                "vars": [("btu", [5000, 6000, 8000, 10000, 12000, 18000]), ("sqft", [150, 250, 350, 450, 550]), ("fan", [2, 3])],
            },
            {
                "name": "{brand} Portable Air Conditioner - {btu} BTU",
                "desc": "3-in-1 portable AC: cools, dehumidifies, and fans. No installation needed. Self-evaporating, continuous drain option.",
                "price_range": (299, 699),
                "specs": lambda btu: {"btu": f"{btu:,}", "modes": "Cool / Dehumidify / Fan", "installation": "No Permanent Install", "self_evaporating": "Yes", "remote": "Yes"},
                "vars": [("btu", [8000, 10000, 12000, 14000])],
            },
            {
                "name": "{brand} Tower Fan - {h}-Inch",
                "desc": "{h}-inch oscillating tower fan. {s} speeds, sleep mode, 8-hour timer. Ultra-quiet for bedrooms.",
                "price_range": (39, 149),
                "specs": lambda h, s: {"height": f"{h} inch", "speeds": str(s), "oscillation": "Yes", "timer": "8 hour", "noise_level": "38-52 dB"},
                "vars": [("h", [36, 40, 42]), ("s", [3, 5, 9])],
            },
            {
                "name": "{brand} Dehumidifier - {p}-Pint",
                "desc": "{p}-pint dehumidifier for spaces up to {sqft} sq ft. Auto-shutoff, continuous drain hose option. Energy Star certified.",
                "price_range": (179, 399),
                "specs": lambda p, sqft: {"capacity": f"{p} pints/day", "coverage": f"{sqft} sq ft", "auto_shutoff": "Yes", "drain_hose": "Optional Continuous", "energy_star": "Yes"},
                "vars": [("p", [22, 30, 35, 50, 70]), ("sqft", [1000, 1500, 2000, 3000])],
            },
        ],
    },
}


# ── Generator helpers ─────────────────────────────────────────────────────────

def escape_sql(s: str) -> str:
    return s.replace("'", "''")

def resolve_vars(template_vars):
    """Return one random combination of variable values."""
    values = {}
    for entry in template_vars:
        key, choices = entry
        values[key] = random.choice(choices)
    return values

def make_product(category: str, brand: str, template: dict, idx: int) -> dict:
    vars_def = template.get("vars", [])
    vals = resolve_vars(vars_def)

    # Build name/desc by substituting {brand} and any var keys
    name_tmpl = template["name"]
    desc_tmpl = template["desc"]

    all_subs = {"brand": brand, **vals}
    name = name_tmpl.format_map(all_subs)
    desc = desc_tmpl.format_map(all_subs)

    # Generate specs dict
    specs_fn = template.get("specs")
    try:
        spec_params = [vals[k] for k, _ in vars_def]
        specs_dict = specs_fn(*spec_params) if spec_params else specs_fn()
    except Exception:
        specs_dict = {}

    # Price
    lo, hi = template["price_range"]
    price = round(random.uniform(lo, hi), 2)
    has_discount = random.random() < 0.4
    original_price = round(price / random.uniform(0.7, 0.95), 2) if has_discount else None

    # Ratings & stock
    rating = round(random.uniform(3.5, 5.0), 1)
    review_count = random.randint(0, 8000)
    stock = random.randint(0, 500)
    is_featured = random.random() < 0.1  # 10% featured

    category_abbr = "".join(w[0] for w in category.split()).upper()
    brand_abbr = brand.replace(" ", "")[:4].upper()
    sku = f"{category_abbr}-{brand_abbr}-{idx:04d}"

    # Image from Picsum (consistent per product, deterministic)
    image_id = (idx * 7 + hash(name)) % 1000
    image_url = f"https://picsum.photos/seed/{abs(image_id)}/400/300"

    return {
        "sku": sku,
        "name": name,
        "description": desc,
        "category": category,
        "brand": brand,
        "price": price,
        "original_price": original_price,
        "stock": stock,
        "rating": rating,
        "review_count": review_count,
        "is_featured": is_featured,
        "specifications": json.dumps(specs_dict) if specs_dict else None,
        "image_url": image_url,
    }


def generate_products(target: int = 1000) -> list[dict]:
    products = []
    idx = 100  # start after manual seeds

    categories = list(CATALOG.keys())
    per_category = math.ceil(target / len(categories))

    for category, cat_data in CATALOG.items():
        brands = cat_data["brands"]
        templates = cat_data["products"]
        count = 0

        while count < per_category and len(products) < target:
            brand = random.choice(brands)
            template = random.choice(templates)
            try:
                p = make_product(category, brand, template, idx)
                products.append(p)
                count += 1
                idx += 1
            except Exception as e:
                pass  # skip malformed entries

    return products[:target]


def to_sql(products: list[dict]) -> str:
    lines = []
    lines.append("-- ============================================================")
    lines.append(f"-- ShopRight Seed Data: {len(products)} Products")
    lines.append("-- Generated by scripts/generate_seed_data.py")
    lines.append("-- ============================================================\n")
    lines.append("INSERT INTO products (sku, name, description, category, brand, price, original_price, stock, rating, review_count, image_url, is_featured, specifications)")
    lines.append("VALUES")

    rows = []
    for p in products:
        op = f"{p['original_price']}" if p["original_price"] else "NULL"
        specs = f"'{escape_sql(p['specifications'])}'" if p["specifications"] else "NULL"
        row = (
            f"  ('{escape_sql(p['sku'])}', '{escape_sql(p['name'])}', '{escape_sql(p['description'])}', "
            f"'{escape_sql(p['category'])}', '{escape_sql(p['brand'])}', {p['price']}, {op}, "
            f"{p['stock']}, {p['rating']}, {p['review_count']}, '{p['image_url']}', "
            f"{'true' if p['is_featured'] else 'false'}, {specs})"
        )
        rows.append(row)

    lines.append(",\n".join(rows))
    lines.append("ON CONFLICT (sku) DO NOTHING;\n")
    lines.append(f"-- Total: {len(products)} products across {len(CATALOG)} categories")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Generating 1000 products...")
    products = generate_products(1000)
    print(f"Generated {len(products)} products")

    # Category breakdown
    from collections import Counter
    cats = Counter(p["category"] for p in products)
    for cat, n in sorted(cats.items()):
        print(f"  {cat}: {n}")

    sql = to_sql(products)

    out_path = Path(__file__).parent.parent / "infra" / "sql" / "seeds.sql"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(sql)
    print(f"\nWritten to {out_path} ({len(sql):,} bytes)")
