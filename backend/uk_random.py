"""英国随机身份数据。

姓名从常见姓名池生成；地址则只从离线核验数据集中整组抽取，绝不随机拼接
街道、城市和邮编，也不在创建客户时调用外部服务。
"""
import csv
import random
from pathlib import Path
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

ADDRESS_DATA_PATH = Path(__file__).with_name("data") / "uk_public_addresses.csv"


def _load_verified_addresses() -> tuple[dict[str, str], ...]:
    """Load the generated, offline-verified public-premises address pool."""
    with ADDRESS_DATA_PATH.open(encoding="utf-8", newline="") as stream:
        rows = tuple({
            "address": row["address"].strip(),
            "city": row["city"].strip(),
            "postcode": row["postcode"].strip().upper(),
        } for row in csv.DictReader(stream))
    if len(rows) < 500:
        raise RuntimeError(f"英国地址池不足 500 条：{len(rows)}")
    if any(not all(row.values()) for row in rows):
        raise RuntimeError("英国地址池包含空字段")
    return rows


# 三个字段必须始终作为不可拆分的一组使用。数据由
# scripts/build_uk_address_pool.py 从英国 FHRS 官方开放 API 生成并离线验证。
REAL_UK_ADDRESSES = _load_verified_addresses()


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
