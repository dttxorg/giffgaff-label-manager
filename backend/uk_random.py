"""英国随机身份数据。

姓名从常见姓名池生成；地址则只从已核验的英国公共机构地址池中整组抽取，
绝不再随机拼接街道、城市和邮编。
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

# 真实英国公共机构地址池。
#
# 地址、城市和邮编在 2026-07-16 依据 OpenStreetMap Nominatim 的公开地点数据整理，
# 并用 Postcodes.io 批量确认邮编当前存在。只使用博物馆等公开机构，不使用私人住宅，
# 避免把随机客户资料指向无关居民。三个字段必须始终作为不可拆分的一组使用。
REAL_UK_ADDRESSES: tuple[dict[str, str], ...] = (
    {"address": "British Museum, Great Russell Street", "city": "London", "postcode": "WC1B 3DG"},
    {"address": "Natural History Museum, Cromwell Road", "city": "London", "postcode": "SW7 5BD"},
    {"address": "Birmingham Museum & Art Gallery, Chamberlain Square", "city": "Birmingham", "postcode": "B3 3DH"},
    {"address": "The Pen Museum, 60 Frederick Street", "city": "Birmingham", "postcode": "B1 3HS"},
    {"address": "Science and Industry Museum, Liverpool Road", "city": "Manchester", "postcode": "M3 4FP"},
    {"address": "The Manchester Museum, Oxford Road", "city": "Manchester", "postcode": "M13 9PL"},
    {"address": "International Slavery Museum, Hartley's Quay", "city": "Liverpool", "postcode": "L3 4AQ"},
    {"address": "Museum of Liverpool, Mann Island", "city": "Liverpool", "postcode": "L3 1AH"},
    {"address": "Abbey House Museum, Abbey Walk", "city": "Leeds", "postcode": "LS5 3EH"},
    {"address": "Leeds City Museum, Millennium Square", "city": "Leeds", "postcode": "LS2 8BH"},
    {"address": "Kelham Island Museum, Alma Street", "city": "Sheffield", "postcode": "S3 8SA"},
    {"address": "Weston Park Museum, Western Bank", "city": "Sheffield", "postcode": "S10 2TP"},
    {"address": "Bristol Museum & Art Gallery, Queens Road", "city": "Bristol", "postcode": "BS8 1RL"},
    {"address": "M Shed, Princes Wharf", "city": "Bristol", "postcode": "BS1 4RN"},
    {"address": "National Justice Museum, High Pavement", "city": "Nottingham", "postcode": "NG1 1HN"},
    {"address": "Nottingham Industrial Museum, Elizabethan Avenue", "city": "Nottingham", "postcode": "NG8 2AE"},
    {"address": "Jewry Wall Museum, Welles Street", "city": "Leicester", "postcode": "LE1 4LR"},
    {"address": "Leicester Museum and Art Gallery, 53 New Walk", "city": "Leicester", "postcode": "LE1 7EA"},
    {"address": "National Museum of Scotland, Chambers Street", "city": "Edinburgh", "postcode": "EH1 1JF"},
    {"address": "Writers' Museum, Lady Stair's Close", "city": "Edinburgh", "postcode": "EH1 2PA"},
    {"address": "Hunterian Museum, North Front", "city": "Glasgow", "postcode": "G12 8LE"},
    {"address": "Kelvingrove Art Gallery and Museum, Argyle Street", "city": "Glasgow", "postcode": "G3 8AG"},
    {"address": "Firing Line Museum, Battlement Walk", "city": "Cardiff", "postcode": "CF10 3RB"},
    {"address": "National Museum Cardiff, Museum Avenue", "city": "Cardiff", "postcode": "CF10 3NP"},
    {"address": "Titanic Belfast, 1 Olympic Way, Queens Road", "city": "Belfast", "postcode": "BT3 9DP"},
    {"address": "Ulster Museum, Stranmillis Road", "city": "Belfast", "postcode": "BT9 5AB"},
    {"address": "Discovery Museum, Blandford Square", "city": "Newcastle upon Tyne", "postcode": "NE1 4JA"},
    {"address": "Great North Museum: Hancock, Barras Bridge", "city": "Newcastle upon Tyne", "postcode": "NE2 4PT"},
    {"address": "Ashmolean Museum, Beaumont Street", "city": "Oxford", "postcode": "OX1 2PH"},
    {"address": "Oxford University Museum of Natural History, Parks Road", "city": "Oxford", "postcode": "OX1 3PW"},
    {"address": "Fitzwilliam Museum, Fitzwilliam Street", "city": "Cambridge", "postcode": "CB2 1QH"},
    {"address": "Museum of Archaeology and Anthropology, Downing Street", "city": "Cambridge", "postcode": "CB2 3DZ"},
    {"address": "National Railway Museum, Leeman Road", "city": "York", "postcode": "YO26 4XJ"},
    {"address": "Yorkshire Museum, Museum Street", "city": "York", "postcode": "YO1 7DR"},
    {"address": "Assembly Rooms and Fashion Museum, Bennett Street", "city": "Bath", "postcode": "BA1 2QH"},
    {"address": "Holburne Museum, Great Pulteney Street", "city": "Bath", "postcode": "BA2 4DB"},
    {"address": "Royal Albert Memorial Museum, Queen Street", "city": "Exeter", "postcode": "EX4 3RX"},
    {"address": "The Bill Douglas Cinema Museum, Prince of Wales Road", "city": "Exeter", "postcode": "EX4 4SB"},
    {"address": "Mary Rose Museum, Main Road", "city": "Portsmouth", "postcode": "PO1 3PY"},
    {"address": "Royal Naval Museum, Main Road", "city": "Portsmouth", "postcode": "PO1 3LU"},
    {"address": "Brighton Museum & Art Gallery, Church Street", "city": "Brighton", "postcode": "BN1 1WN"},
    {"address": "Brighton Toy and Model Museum, 52-55 Trafalgar Street", "city": "Brighton", "postcode": "BN1 4EB"},
    {"address": "Aberdeen Maritime Museum, 52-56 Shiprow", "city": "Aberdeen", "postcode": "AB11 5BY"},
    {"address": "King's Museum, High Street", "city": "Aberdeen", "postcode": "AB24 3EE"},
    {"address": "D'Arcy Thompson Zoology Museum, Nethergate", "city": "Dundee", "postcode": "DD1 4HN"},
    {"address": "Dundee Museum of Transport, Unit 10, Market Street", "city": "Dundee", "postcode": "DD1 3LA"},
    {"address": "Mayflower Museum, 3-5 The Barbican", "city": "Plymouth", "postcode": "PL1 2LR"},
    {"address": "The Box, Tavistock Place", "city": "Plymouth", "postcode": "PL4 8AX"},
    {"address": "Coventry Transport Museum, Hales Street", "city": "Coventry", "postcode": "CV1 1JD"},
    {"address": "Herbert Art Gallery & Museum, Jordan Well", "city": "Coventry", "postcode": "CV1 5QP"},
    {"address": "Derby Museum and Art Gallery, The Strand", "city": "Derby", "postcode": "DE1 1BS"},
    {"address": "Pickford's House Museum, 41 Friar Gate", "city": "Derby", "postcode": "DE1 1DA"},
    {"address": "SeaCity Museum, Havelock Road", "city": "Southampton", "postcode": "SO14 7FY"},
    {"address": "Tudor House Museum, Bugle Street", "city": "Southampton", "postcode": "SO14 2AL"},
    {"address": "Museum of English Rural Life, Acacia Road", "city": "Reading", "postcode": "RG1 5EY"},
    {"address": "Reading Museum, Valpy Street", "city": "Reading", "postcode": "RG1 1QH"},
    {"address": "Tettenhall Transport Heritage Museum, Henwood Road", "city": "Wolverhampton", "postcode": "WV6 8NX"},
    {"address": "Wolves Museum and Stadium Tours, Waterloo Road", "city": "Wolverhampton", "postcode": "WV1 4QR"},
    {"address": "Gladstone Pottery Museum, Uttoxeter Road", "city": "Stoke-on-Trent", "postcode": "ST3 1PQ"},
    {"address": "Potteries Museum and Art Gallery, Bethesda Street", "city": "Stoke-on-Trent", "postcode": "ST1 3DW"},
)


def generate_first_name() -> str:
    return random.choice(FIRST_NAMES)


def generate_last_name() -> str:
    return random.choice(LAST_NAMES)


def generate_address() -> str:
    """从核验地址池返回一个真实存在的完整地址行。"""
    return random.choice(REAL_UK_ADDRESSES)["address"]


def generate_postcode(prefix: Optional[str] = None) -> str:
    """从核验地址池返回真实邮编，可按邮编开头筛选。

    ``prefix`` 仅保留旧调用方式的兼容性，例如 ``SW`` 或 ``SW7``；找不到真实
    邮编时明确报错，而不是伪造一个看似合法的邮编。
    """
    candidates = REAL_UK_ADDRESSES
    if prefix is not None:
        normalized = prefix.strip().upper()
        candidates = tuple(
            location for location in REAL_UK_ADDRESSES
            if location["postcode"].startswith(normalized)
        )
        if not candidates:
            raise ValueError(f"没有已核验的英国邮编匹配前缀 {prefix!r}")
    return random.choice(candidates)["postcode"]


def generate_random_identity() -> dict:
    """生成姓名，并整组抽取真实地址、城市和邮编。"""
    location = random.choice(REAL_UK_ADDRESSES)
    return {
        "first_name": generate_first_name(),
        "last_name": generate_last_name(),
        "address": location["address"],
        "city": location["city"],
        "postcode": location["postcode"],
    }
