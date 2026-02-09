from app.config import settings

def main():
    tier = settings.get_tier("free")

    print("Redis:", settings.env.redis_url)
    print("Tier:", tier.name)
    print("Limit:", tier.limit)
    print("Window:", tier.window)


if __name__ == "__main__":
    main()
