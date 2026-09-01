from database.db import db

print("Testing Footage Categories in SQLite Database:")
all_footages = db.get_all_footages()
print(f"Total footages: {len(all_footages)}")

for f in all_footages[:5]:
    print(f"  - ID: {f['id']}, File: {f['filename']}, Category: {f.get('category')}")

cars = db.get_all_footages(category="cars")
print(f"\nCars category count: {len(cars)}")

football = db.get_all_footages(category="football")
print(f"Football category count: {len(football)}")

beauty = db.get_all_footages(category="beauty")
print(f"Beauty category count: {len(beauty)}")
