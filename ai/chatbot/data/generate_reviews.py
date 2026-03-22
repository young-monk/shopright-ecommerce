"""
Generates realistic product reviews for all 1000 ShopRight products.
Output: ai/chatbot/data/reviews.json

Each product gets 3-5 reviews with ratings distributed around the product's
actual average rating from the catalog. Reviews are category-aware and
reference real product specs.

Run: python3 generate_reviews.py
"""

import re
import json
import random
from datetime import datetime, timedelta

random.seed(42)

# ── Parse seeds.sql ────────────────────────────────────────────────────────────

SQL_PATH = "../../../infra/sql/seeds.sql"

def parse_products(path):
    text = open(path).read()
    # Match: (sku, name, description, category, brand, price, orig_price, stock, rating, reviews, ...)
    pattern = (
        r"\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*"
        r"'([^']+)',\s*'([^']+)',\s*"
        r"([0-9.]+),\s*([0-9.]+|NULL),\s*([0-9]+),\s*([0-9.]+),\s*([0-9]+),"
        r".*?'(\{[^']*\})'\)"
    )
    products = []
    for m in re.finditer(pattern, text, re.DOTALL):
        sku, name, desc, cat, brand, price, orig, stock, rating, reviews, specs = m.groups()
        try:
            spec_dict = json.loads(specs)
        except Exception:
            spec_dict = {}
        products.append({
            "sku": sku,
            "name": name,
            "description": desc,
            "category": cat,
            "brand": brand,
            "price": float(price),
            "rating": float(rating),
            "review_count": int(reviews),
            "specs": spec_dict,
        })
    return products

# ── Review templates per category ─────────────────────────────────────────────

FIRST_NAMES = [
    "James", "Maria", "Kevin", "Sandra", "Tom", "Linda", "Chris", "Patricia",
    "David", "Jennifer", "Michael", "Barbara", "Robert", "Susan", "William",
    "Jessica", "Richard", "Sarah", "Joseph", "Karen", "Carlos", "Angela",
    "Daniel", "Michelle", "Mark", "Emily", "Paul", "Amanda", "Andrew", "Melissa",
    "Ryan", "Deborah", "Josh", "Stephanie", "Tyler", "Rebecca", "Nathan", "Sharon",
    "Eric", "Laura", "Brian", "Cynthia", "Greg", "Kathleen", "Sean", "Amy",
    "Derek", "Anna", "Aaron", "Brenda", "Kyle", "Emma", "Justin", "Nicole",
]

LAST_INITIALS = list("ABCDEFGHJKLMNPRSTW")

def reviewer():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_INITIALS)}."

def random_date():
    days_ago = random.randint(3, 730)
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def random_verified():
    return random.random() < 0.82

def star_distribution(avg_rating, n):
    """Return n star values that average close to avg_rating."""
    stars = []
    for _ in range(n):
        # Gaussian around avg, clamped to 1-5
        s = round(random.gauss(avg_rating, 0.8))
        stars.append(max(1, min(5, s)))
    return stars


# ── Category-specific review pools ────────────────────────────────────────────

def reviews_power_tools(product, stars_list):
    name = product["name"]
    brand = product["brand"]
    specs = product["specs"]
    out = []

    openers_5 = [
        f"This {brand} is an absolute workhorse.",
        f"Best power tool purchase I've made in years.",
        f"Exceeded my expectations right out of the box.",
        f"Solid build quality and serious power for the price.",
        f"A contractor friend recommended this and I'm glad I listened.",
    ]
    openers_4 = [
        f"Really solid tool, a couple of minor nitpicks.",
        f"Great performance — just wish the battery lasted a bit longer.",
        f"Good tool overall, does exactly what it says.",
        f"Happy with this purchase, minor room for improvement.",
    ]
    openers_3 = [
        f"Decent tool for the price, nothing groundbreaking.",
        f"Works fine but feels a bit plasticky.",
        f"Gets the job done, but I expected better from {brand}.",
        f"Mediocre — not bad, not great.",
    ]
    openers_low = [
        f"Disappointed with this one.",
        f"Had higher hopes based on the reviews.",
        f"Returned after two uses — quality control issue.",
        f"Chuck wobbles after just a few weeks of use.",
    ]

    middles = [
        f"Used it to build a 400 sq ft deck and it held up the entire time.",
        f"The LED work light is genuinely useful in dark spaces.",
        f"Battery charges fast — back to full in under an hour.",
        f"Variable speed trigger gives great control for delicate work.",
        f"Fits comfortably in my hand even after hours of use.",
        f"Runs quieter than my old corded model.",
        f"The carrying case keeps everything organized in my truck.",
        f"Drove through 3-inch structural screws without breaking a sweat.",
        f"The clutch settings work exactly as advertised — no more stripped screws.",
        f"Noticeably lighter than my old 18V, which matters on overhead work.",
    ]

    if "voltage" in specs:
        v = specs["voltage"]
        middles.append(f"The {v} battery has plenty of juice for a full day of framing.")
    if "max_torque" in specs:
        middles.append(f"Rated at {specs['max_torque']} torque and you can feel every bit of it.")
    if "strokes_per_min" in specs:
        middles.append(f"At {specs['strokes_per_min']} SPM it rips through material fast.")

    closers = [
        "Would buy again.", "Highly recommend to any DIYer.", "My go-to for every project now.",
        "Great value for the money.", "Worth every dollar.",
        "Solid choice if you're in the market for this type of tool.",
        "Two thumbs up from a weekend warrior.",
    ]

    complaints = [
        "The included bits are cheap — buy aftermarket ones.",
        "Battery indicator LED is hard to read in bright sunlight.",
        "Wish it came with a belt clip.",
        "A bit louder than expected.",
        "The case latches feel flimsy.",
    ]

    for stars in stars_list:
        if stars >= 5:
            body = f"{random.choice(openers_5)} {random.choice(middles)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Top-notch tool", "Exactly what I needed", "Highly recommend", "Solid performer", "Great buy"])
        elif stars == 4:
            body = f"{random.choice(openers_4)} {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Good tool, minor gripes", "4 stars — almost perfect", "Solid but not flawless", "Good value"])
        elif stars == 3:
            body = f"{random.choice(openers_3)} {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["It's okay", "Average", "Does the job", "Fine for occasional use"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)} {random.choice(complaints)}"
            title = random.choice(["Not impressed", "Disappointing", "Had issues", "Expected more"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_hand_tools(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        f"The best {name.lower()} I've ever owned.",
        f"{brand} quality is always top tier.",
        "Lifetime guarantee gives me real peace of mind.",
        "These have been in my toolbox for six months and still look new.",
    ]
    openers_4 = [
        "Good tools, slightly overpriced but you get what you pay for.",
        "Solid build, grips comfortably.",
        "My go-to brand — this set lives up to the name.",
    ]
    openers_low = [
        "Handle cracked on the third use.",
        "Chrome finish started peeling within a month.",
        "Fit is loose on smaller fasteners.",
    ]
    middles = [
        "The grip is comfortable even after hours of use.",
        "Fits snugly on every fastener I've tried — no slipping.",
        "Perfect balance — not too heavy, not too light.",
        "I've dropped these off a roof twice and they're fine.",
        "Used daily on a remodel project and they held up great.",
        "The case keeps them organized and prevents scratching.",
        "Great addition to my professional toolkit.",
        "Better leverage than my previous brand.",
    ]
    closers = ["Highly recommend.", "Would buy again.", "Great value.", "A solid investment."]
    complaints = [
        "Wish the set included more sizes.",
        "The bag/case feels cheap for the price.",
        "Markings wore off after a few months.",
        "Slightly loose fit on metric fasteners.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Great quality", "Professional grade", "My new favorite", "Solid set"])
        elif stars == 3:
            body = f"Decent set. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Fine for the price", "Okay", "Decent"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Disappointed", "Quality issues", "Not durable"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_plumbing(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Plumber friend told me this was the best choice and he was right.",
        "Installed in under 30 minutes — no leaks after 6 months.",
        f"{brand} makes quality products and this is no exception.",
        "Solid construction, easy install.",
    ]
    openers_4 = [
        "Works great, installation instructions could be clearer.",
        "Good product but the supply lines weren't included.",
        "Solid — just wish the finish were a bit more durable.",
    ]
    openers_low = [
        "Developed a slow drip at the connection point within 3 months.",
        "Handle feels cheap for the price.",
        "Finish started spotting after two weeks.",
    ]
    middles = [
        "The installation was straightforward — shut off, swap, done.",
        "Everything needed was in the box except the supply lines.",
        "Water flow is strong and temperature control is precise.",
        "No leaks after 8 months — very happy.",
        "The finish matches our other fixtures perfectly.",
        "Cleaned up the look of our kitchen significantly.",
        "Meets or exceeds what I expected at this price point.",
    ]
    closers = ["Would recommend to any DIYer.", "Great value.", "Happy with this purchase."]
    complaints = [
        "Supply lines sold separately — budget for that.",
        "Handle hardware could be heavier.",
        "Instructions are vague on the supply connection step.",
        "Mounting hardware is just okay.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Easy install, no leaks", "Great product", "Works perfectly", "Solid plumbing upgrade"])
        elif stars == 3:
            body = f"Works as advertised. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Decent", "Gets the job done", "Fine for the price"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Quality issues", "Disappointing", "Had leaks"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_electrical(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Electrician-grade quality at a homeowner price.",
        "Perfect fit, professional finish.",
        "Easy to install if you know basic wiring.",
        f"{brand} reliability — exactly what I expected.",
    ]
    openers_4 = [
        "Works great, app setup was a little clunky.",
        "Good product — instructions assume you already know what you're doing.",
        "Solid — minor gripe with the app pairing process.",
    ]
    openers_low = [
        "Stopped working after two months.",
        "App connectivity is unreliable.",
        "Didn't fit standard single-gang box without modification.",
    ]
    middles = [
        "Installed three of these throughout the house — all working great.",
        "The tamper-resistant shutters work exactly as described.",
        "App pairing was simple and works reliably on my Wi-Fi.",
        "Replaced 12 outlets in my bathroom remodel — no issues.",
        "Huge energy savings compared to my old incandescent setup.",
        "The occupancy indicator light is a nice touch.",
        "Solid build — feels more premium than the price suggests.",
    ]
    closers = ["Would buy again.", "Highly recommend.", "Great value for the money."]
    complaints = [
        "App interface is dated but functional.",
        "Neutral wire required — most older homes need an adapter.",
        "Screws are small and easy to drop in a wall cavity.",
        "LED flicker on some bulb brands at low dim levels.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Great electrical upgrade", "Works perfectly", "Easy install", "Solid product"])
        elif stars == 3:
            body = f"Works as expected. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Decent", "Fine for the price"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Had issues", "Disappointing", "Stopped working"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_flooring(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Installed 600 sq ft myself over a weekend — turned out beautiful.",
        f"{brand} quality is evident the moment you open the box.",
        "Our guests always compliment the flooring — best home upgrade we've made.",
        "Planks are thick, consistent, and the color is exactly as shown.",
    ]
    openers_4 = [
        "Looks great, installation was a bit tricky at the walls.",
        "Very happy overall — just a few boards had minor defects.",
        "Good product, acclimation instructions were vague.",
    ]
    openers_low = [
        "Color looked different in person than online.",
        "Two boxes had warped planks — had to return them.",
        "Edges chipped during cutting — may need a better blade.",
    ]
    middles = [
        "The click-lock system went together smoothly with no gaps.",
        "Used it in a basement with a moisture barrier and it's held up perfectly.",
        "Grout lines are sharp and clean — very professional look.",
        "Standing on it all day in the kitchen and my feet don't ache.",
        "Matches the color in the online photo very closely.",
        "The texture hides minor scratches well.",
        "Our dog doesn't slip on it and it resists scratches surprisingly well.",
    ]
    closers = ["Would buy again.", "Highly recommend for DIY installation.", "Great value per square foot."]
    complaints = [
        "Buy 15% extra — we ran short on the last room.",
        "Acclimate for at least 48 hours or you'll get gaps.",
        "Color varies slightly between boxes — mix them as you go.",
        "Cutting tiles required a wet saw — budget for that.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Beautiful flooring", "Great DIY install", "Looks amazing", "Highly recommend"])
        elif stars == 3:
            body = f"Decent flooring. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Good but not perfect", "Fine for the price"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Quality issues", "Not as advertised", "Disappointed"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_paint(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        f"{brand} has been my go-to paint brand for 10 years.",
        "Two coats and full coverage — didn't need a third.",
        "The color matched the chip perfectly.",
        "Used this for our whole-house repaint — stunning results.",
    ]
    openers_4 = [
        "Good coverage but needed a third coat on the darker accent wall.",
        "Great paint, a bit pricey but worth it.",
        "Solid product — dry time is slightly longer than stated.",
    ]
    openers_low = [
        "Coverage was poor — needed 4 coats to cover a medium gray.",
        "Color dried 2 shades darker than the chip.",
        "Brush marks were visible even after thinning.",
    ]
    middles = [
        "Went on smoothly with a 3/8-inch roller — no lap marks.",
        "Dried to a beautiful even sheen.",
        "No strong odor — comfortable to use in a closed room.",
        "Very washable — marker wiped off our kid's bedroom wall easily.",
        "Great leveling — brush strokes flowed out nicely.",
        "Two gallons covered our 12x15 living room with two coats to spare.",
    ]
    closers = ["Would buy again.", "Highly recommend.", "Will use for every room going forward."]
    complaints = [
        "Dry time between coats is longer than most brands.",
        "More expensive than big-box house brands but worth the quality.",
        "Stir well before each use — separates in the can.",
        "Sheen level is slightly higher than I expected for 'satin'.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Great coverage", "Beautiful finish", "My go-to paint", "Excellent quality"])
        elif stars == 3:
            body = f"Decent paint. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Good but pricey", "Average coverage"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Poor coverage", "Color mismatch", "Disappointing"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_outdoor(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        f"Best {brand.lower()} product I've bought for the yard.",
        "Makes yard work actually enjoyable.",
        "Powerful, lightweight, and easy to start.",
        "Replaced my old gas model and haven't looked back.",
    ]
    openers_4 = [
        "Works great — battery life is the only real gripe.",
        "Good performance, just wish it included an extra battery.",
        "Solid tool, a couple of minor design quibbles.",
    ]
    openers_low = [
        "Battery didn't hold a charge after 4 months.",
        "Motor burned out on thick wet grass.",
        "Plastic housing cracked after a minor drop.",
    ]
    middles = [
        "Handles thick grass and weeds without bogging down.",
        "Much quieter than the gas version — neighbors love me now.",
        "Easy to start every time — just press the button.",
        "The adjustable handle height makes it comfortable for my whole family.",
        "Folded up for compact storage in my small garage.",
        "Battery charges in about an hour and lasts my whole half-acre.",
        "Assembly took 10 minutes with the included tools.",
    ]
    closers = ["Would highly recommend.", "A great investment for any homeowner.", "Will buy from this brand again."]
    complaints = [
        "Included battery runs out faster than the stated runtime.",
        "Bagger fills up quickly on thick grass.",
        "Height adjustment lever is a bit stiff.",
        "Doesn't handle slopes very well.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Love it", "Great yard tool", "Game changer", "Solid performer"])
        elif stars == 3:
            body = f"Does the job. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Good enough", "Works but could be better"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Broke too soon", "Battery issues", "Not durable"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_safety(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Peace of mind you can't put a price on.",
        f"{brand} is the brand professionals trust.",
        "Easy to install — up and running in 20 minutes.",
        "Fantastic image quality — I can read license plates at 40 feet.",
    ]
    openers_4 = [
        "Works great — app could use some polish.",
        "Good system, cloud storage adds up in cost over time.",
        "Solid product, setup was a bit involved.",
    ]
    openers_low = [
        "App crashes every few days.",
        "Night vision range is underwhelming.",
        "Motion alerts fire constantly on windy days.",
    ]
    middles = [
        "Image clarity is excellent day and night.",
        "App notifications are instant — no noticeable delay.",
        "Setup was straightforward with the included instructions.",
        "Weatherproof housing held up through an entire winter.",
        "The wide-angle lens covers more than I expected.",
        "Paired with my smart home system without any issues.",
        "Two-way audio is clear and useful.",
    ]
    closers = ["Highly recommend for home security.", "Worth every dollar.", "Will add more cameras soon."]
    complaints = [
        "App interface is a bit dated.",
        "Wi-Fi signal needs to be strong at the mount location.",
        "Cloud subscription fees add up over time.",
        "Motion sensitivity tuning takes some trial and error.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Great security upgrade", "Works perfectly", "Easy install", "Excellent camera"])
        elif stars == 3:
            body = f"Does the job. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Decent security cam", "Good enough"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["App issues", "Not impressed", "Had problems"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_hvac(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Cooled my 300 sq ft bedroom perfectly all summer.",
        f"Buying {brand} was a great decision — quiet and powerful.",
        "Energy costs dropped noticeably after switching to this.",
        "Installation was quick — in the window and cooling in 10 minutes.",
    ]
    openers_4 = [
        "Works great — a bit louder than expected at max setting.",
        "Good unit, remote control could be more intuitive.",
        "Happy with the purchase — app setup was a minor headache.",
    ]
    openers_low = [
        "Compressor is noticeably loud at night.",
        "Didn't cool the room as advertised.",
        "Thermostat reads 2-3 degrees off.",
    ]
    middles = [
        "Set to 70° and it held that temp all night — great sleep.",
        "Energy Saver mode is genuinely useful and cuts noise.",
        "The timer function lets me cool the room before I get home.",
        "Dehumidification noticeably improved the room comfort.",
        "Quieter than my previous window unit — can sleep through it.",
        "App control from anywhere is a huge convenience.",
        "Drainage hose kit works well for continuous operation.",
    ]
    closers = ["Would recommend.", "A great buy for hot summers.", "Will purchase another for a second room."]
    complaints = [
        "Installation requires two people — it's heavier than it looks.",
        "Drain pan needs emptying every day in peak humidity.",
        "Remote loses line-of-sight around corners.",
        "Filter is a bit awkward to access for cleaning.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Keeps us cool", "Great AC unit", "Excellent performance", "Quiet and powerful"])
        elif stars == 3:
            body = f"Works okay. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Fine for the price", "Decent unit", "Does the job"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Too loud", "Underperforms", "Disappointed"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_storage(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Finally got my garage organized — this system is worth every penny.",
        f"{brand} quality shows the moment you open the box.",
        "Solid steel, smooth drawer slides, excellent value.",
        "Transformed my chaotic garage into a real workshop.",
    ]
    openers_4 = [
        "Great chest — drawer slides feel a little light on the bottom row.",
        "Looks great, minor assembly instructions issue.",
        "Very happy overall — one drawer needed adjustment out of the box.",
    ]
    openers_low = [
        "Drawer slides feel flimsy for the price.",
        "One drawer arrived dented.",
        "Paint finish scratched easily during assembly.",
    ]
    middles = [
        "Ball-bearing slides are buttery smooth.",
        "Holds significantly more than my previous chest.",
        "Powder coat finish is holding up well after 8 months.",
        "Each drawer holds a surprising amount of weight.",
        "The lock keeps my tools secure when my kids are in the garage.",
        "Mounted on a workbench and it hasn't budged.",
        "Color matches my other garage storage units perfectly.",
    ]
    closers = ["Would buy again.", "Great garage upgrade.", "Highly recommended for any tool collector."]
    complaints = [
        "Assembly instructions could use clearer diagrams.",
        "The casters feel light for a heavy load.",
        "Key lock is basic — not high security.",
        "Drawer pulls could be chunkier.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Great garage storage", "Excellent tool chest", "Organized my garage", "Solid and sturdy"])
        elif stars == 3:
            body = f"Decent chest. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Fine for the price", "Good but not great"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Quality issues", "Disappointing", "Not worth it"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


def reviews_building(product, stars_list):
    brand = product["brand"]
    name = product["name"]
    out = []
    openers_5 = [
        "Professional quality at a great price.",
        "Structural connectors that actually do what they promise.",
        "These fasteners are what contractors use — now I know why.",
        "Used on a full deck build and I trust them completely.",
    ]
    openers_4 = [
        "Good product — directions for the connector install were vague.",
        "Works as advertised, just wish it came in larger pack sizes.",
        "Solid material — minor packaging issue on arrival.",
    ]
    openers_low = [
        "Screws stripped easier than expected.",
        "Packaging was damaged — some hardware missing.",
        "Finish quality not up to the price.",
    ]
    middles = [
        "Every piece was exactly as spec'd.",
        "Fit standard lumber dimensions perfectly.",
        "Galvanized coating looks durable for outdoor use.",
        "Used these for a pergola build and they're rock solid.",
        "Pre-drilled holes are positioned well for a clean installation.",
        "Vapor barrier rolled out easily and sealed well with tape.",
        "Drywall cut cleanly and accepted screws without cracking.",
    ]
    closers = ["Will order again.", "Recommend for any structural project.", "Great quality fasteners."]
    complaints = [
        "Galvanized coating is thinner than I'd like for coastal exposure.",
        "Packs could be larger — had to order twice.",
        "Instructions assume prior experience with structural connectors.",
    ]
    for stars in stars_list:
        if stars >= 4:
            body = f"{random.choice(openers_4 if stars == 4 else openers_5)} {random.choice(middles)} {random.choice(closers)}"
            title = random.choice(["Solid materials", "Great fasteners", "Pro quality", "Highly recommend"])
        elif stars == 3:
            body = f"Works fine. {random.choice(middles)} {random.choice(complaints)}"
            title = random.choice(["Okay", "Does the job", "Fine for the price"])
        else:
            body = f"{random.choice(openers_low)} {random.choice(complaints)}"
            title = random.choice(["Quality issues", "Not as described", "Disappointed"])
        out.append({"stars": stars, "title": title, "body": body.strip(),
                    "author": reviewer(), "date": random_date(), "verified": random_verified()})
    return out


CATEGORY_FN = {
    "Power Tools":          reviews_power_tools,
    "Hand Tools":           reviews_hand_tools,
    "Plumbing":             reviews_plumbing,
    "Electrical":           reviews_electrical,
    "Flooring":             reviews_flooring,
    "Paint & Supplies":     reviews_paint,
    "Outdoor & Garden":     reviews_outdoor,
    "Safety & Security":    reviews_safety,
    "Heating & Cooling":    reviews_hvac,
    "Storage & Organization": reviews_storage,
    "Building Materials":   reviews_building,
}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    products = parse_products(SQL_PATH)
    print(f"Loaded {len(products)} products")

    output = []
    for p in products:
        # 3-5 reviews per product
        n = random.choices([3, 4, 4, 5], weights=[1, 3, 3, 2])[0]
        stars_list = star_distribution(p["rating"], n)

        fn = CATEGORY_FN.get(p["category"], reviews_hand_tools)
        reviews = fn(p, stars_list)

        # Compute the generated average for transparency
        gen_avg = round(sum(r["stars"] for r in reviews) / len(reviews), 1)

        output.append({
            "sku":       p["sku"],
            "name":      p["name"],
            "category":  p["category"],
            "brand":     p["brand"],
            "price":     p["price"],
            "catalog_rating": p["rating"],
            "generated_avg":  gen_avg,
            "reviews":   reviews,
        })

    out_path = "reviews.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    total_reviews = sum(len(p["reviews"]) for p in output)
    print(f"Written {len(output)} products, {total_reviews} total reviews → {out_path}")


if __name__ == "__main__":
    main()
