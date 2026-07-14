"""UK 风格随机数据：人名 / 地址 / 城市 / 邮编。
用于客户创建后自动填充占位信息。
"""
import random
from typing import Optional

# 100 个常见英文 first names（混合男女）
FIRST_NAMES = [
    "Oliver", "George", "Harry", "Jack", "Jacob", "Noah", "Charlie", "Muhammad",
    "Thomas", "Oscar", "William", "James", "Henry", "Leo", "Alfie", "Joshua",
    "Ethan", "Joseph", "Freddie", "Samuel", "Isaac", "Alexander", "Daniel", "Logan",
    "Edward", "Lucas", "Max", "Mason", "Harrison", "Theo", "Finn", "Sebastian",
    "Adam", "Dylan", "Zachary", "Archer", "Hunter", "Jackson", "Liam", "Jake",
    "Harvey", "Carter", "Owen", "Ryan", "Tyler", "Jayden", "Nathan", "Kai",
    "Amelia", "Olivia", "Isla", "Emily", "Poppy", "Ava", "Isabella", "Jessica",
    "Lily", "Sophie", "Grace", "Sophia", "Mia", "Evie", "Ruby", "Ella",
    "Scarlett", "Sienna", "Hannah", "Evelyn", "Lucy", "Maya", "Layla", "Zara",
    "Daisy", "Holly", "Phoebe", "Alice", "Lola", "Molly", "Ellie", "Rosie",
    "Bella", "Eva", "Emilia", "Harriet", "Erin", "Jasmine", "Elsie", "Charlotte",
    "Matilda", "Ivy", "Sara", "Naomi", "Lydia", "Aisha", "Maryam", "Fatima",
]

# 100 个常见英文 surnames
LAST_NAMES = [
    "Smith", "Jones", "Taylor", "Brown", "Wilson", "Evans", "Walker", "Wright",
    "Roberts", "Johnson", "Lewis", "Robinson", "Wood", "Thompson", "White", "Watson",
    "Edwards", "Hughes", "Green", "Hall", "Clarke", "Clark", "Mitchell", "Carter",
    "Phillips", "Turner", "Parker", "Harris", "Martin", "Davis", "Bennett", "Foster",
    "Cooper", "Ward", "Hughes", "Gray", "King", "Baker", "Allen", "Hill",
    "Stone", "Harrison", "Murray", "Simpson", "Cole", "Stevens", "Moore", "Mason",
    "Owen", "Hunt", "Holmes", "Russell", "Palmer", "Mills", "Barker", "Stewart",
    "Murray", "Graham", "Grant", "Fisher", "Wells", "Stone", "Palmer", "Andrews",
    "Barnes", "Baxter", "Brennan", "Burke", "Burns", "Byrne", "Carroll", "Casey",
    "Chambers", "Chapman", "Chester", "Choi", "Conner", "Conway", "Cunningham", "Daly",
    "Duncan", "Ellis", "Fitzgerald", "Fleming", "Ford", "Fraser", "Gallagher", "Garcia",
    "Gibson", "Gordon", "Graham", "Hamilton", "Hardy", "Harper", "Hayes", "Henderson",
]

# 50 个常见 UK 街道名
STREET_NAMES = [
    "High Street", "Station Road", "Main Street", "Park Road", "Church Lane",
    "Church Street", "Victoria Road", "Manor Road", "London Road", "Park Avenue",
    "The Avenue", "Queens Road", "Kings Road", "New Road", "Mill Lane",
    "School Lane", "Springfield Road", "Windsor Road", "Green Lane", "Manor Way",
    "Heath Road", "Oak Drive", "Elm Close", "Cedar Avenue", "Maple Way",
    "Willow Road", "Birch Avenue", "Cherry Tree Lane", "Holly Walk", "Ivy Close",
    "Rose Hill", "Garden Street", "Orchard Way", "Meadow View", "Riverside Drive",
    "Bridge Street", "Castle Road", "Castle Street", "Church Road", "Marlborough Road",
    "Cambridge Road", "Oxford Road", "Regent Street", "Bond Street", "Baker Street",
    "Piccadilly", "Downing Street", "Whitehall", "Fleet Street", "Strand",
]

# UK 邮编前缀（按城市区域）
# UK 城市 → 邮编前缀的映射。生成 random_identity 时按这个表选邮编，
# 保证 postcode 一定对应 city（giffgaff 等表单会校验）。
CITY_POSTCODES: dict[str, list[str]] = {
    "London": ["SW", "NW", "N", "E", "W", "SE", "EC", "WC"],
    "Manchester": ["M", "OL", "BL"],
    "Birmingham": ["B"],
    "Leeds": ["LS", "WF"],
    "Glasgow": ["G", "PA"],
    "Liverpool": ["L", "CH"],
    "Newcastle": ["NE", "DH"],
    "Sheffield": ["S"],
    "Bristol": ["BS", "BA"],
    "Nottingham": ["NG"],
    "Leicester": ["LE"],
    "Edinburgh": ["EH", "FK"],
    "Southampton": ["SO"],
    "Portsmouth": ["PO"],
    "Brighton": ["BN"],
    "Oxford": ["OX"],
    "Cambridge": ["CB"],
    "Reading": ["RG"],
    "York": ["YO"],
    "Bath": ["BA"],
    "Exeter": ["EX"],
    "Cardiff": ["CF"],
    "Belfast": ["BT"],
    "Aberdeen": ["AB"],
    "Dundee": ["DD"],
    "Plymouth": ["PL"],
    "Coventry": ["CV"],
    "Wolverhampton": ["WV"],
    "Stoke-on-Trent": ["ST"],
    "Derby": ["DE"],
}


def generate_first_name() -> str:
    return random.choice(FIRST_NAMES)


def generate_last_name() -> str:
    return random.choice(LAST_NAMES)


def generate_address() -> str:
    """返回 '42 Baker Street' 或 'Flat 3, 17 Station Road' 这种。"""
    house_number = random.randint(1, 200)
    street = random.choice(STREET_NAMES)
    if random.random() < 0.3:
        flat = f"Flat {random.randint(1, 30)}"
        return f"{flat}, {house_number} {street}"
    return f"{house_number} {street}"


def generate_postcode(prefix: Optional[str] = None) -> str:
    """UK postcode 格式：字母 + 数字 + 空格 + 数字 + 字母 + 字母（如 SW1A 1AA）。
    不传 prefix 时从所有 CITY_POSTCODES 里随机选一个区——这种用法不应出现在生产路径，
    因为它可能产生不匹配 city 的 postcode。"""
    if prefix is None:
        all_prefixes = [p for ps in CITY_POSTCODES.values() for p in ps]
        prefix = random.choice(all_prefixes)
    digit1 = random.randint(1, 99)
    letter1 = random.choice("ABCDEFGHJKLMNOPRSTUVWXYZ")
    digit2 = random.randint(0, 9)
    letter2 = random.choice("ABCDEFGHJKLMNOPRSTUVWXYZ")
    letter3 = random.choice("ABCDEFGHJKLMNOPRSTUVWXYZ")
    return f"{prefix}{digit1} {letter1}{digit2}{letter2}{letter3}"


def generate_random_identity() -> dict:
    """一次性生成完整身份信息（5 个字段）。
    直接从 CITY_POSTCODES 里抽 (city, prefix) 对子——这样 city 和 postcode 永远 1:1 对应，
    不会落到「CITY_POSTCODES 里没这个城市」的边界 case。"""
    first_name = generate_first_name()
    last_name = generate_last_name()
    address = generate_address()
    city, prefix = random.choice(list(CITY_POSTCODES.items()))
    prefix = random.choice(prefix)  # 一个城市可能对应多个邮编区
    postcode = generate_postcode(prefix=prefix)
    return {
        "first_name": first_name,
        "last_name": last_name,
        "address": address,
        "city": city,
        "postcode": postcode,
    }
