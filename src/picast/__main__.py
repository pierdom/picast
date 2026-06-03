import asyncio

from picast.app import App


def main() -> None:
    try:
        asyncio.run(App().run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
