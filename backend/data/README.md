# UK address pool

`uk_public_addresses.csv` contains public-facing UK business-premises addresses.
It is generated data, not a manually maintained list and not Faker output.

Sources and checks:

- Address fields: UK Food Standards Agency Food Hygiene Rating Scheme open-data API
  (`https://api.ratings.food.gov.uk`)
- Postcode existence check: Postcodes.io bulk API
- Scope: 600 unique premises, 30 cities, 20 premises per city
- Private/mobile premises are filtered out; every retained address includes a premise
  or unit number and a complete UK postcode.

Refresh the pool from the repository root:

```bash
python3 scripts/build_uk_address_pool.py --target 600
```

The generator fetches data only during this maintenance command. Customer creation
loads the bundled CSV and does not depend on either external API.
