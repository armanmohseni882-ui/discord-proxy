import asyncio
import aiohttp
import argparse
import json

async def test_api_call(api_key, base_url, endpoint, params):
    """
    A simple script to test connectivity to the balldontlie API
    and to inspect the structure of the response.
    """
    if not api_key:
        print("Error: API key must be provided.")
        return

    url = f"{base_url}{endpoint}"
    headers = {"Authorization": api_key}

    print(f"Making request to: {url} with params: {params}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                print("\n--- API Response ---")
                print(json.dumps(data, indent=2))
                print("--- End of Response ---\n")

                if isinstance(data, dict) and data.get("data"):
                    print(f"Successfully found {len(data['data'])} items.")
                else:
                    print("Request was successful, but no data array found.")

        except aiohttp.ClientError as e:
            print(f"An error occurred during the API request: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test balldontlie API endpoints.")
    parser.add_argument("--api-key", required=True, help="Your balldontlie API key.")
    parser.add_argument("--base-url", default="https://api.balldontlie.io/v1", help="The base URL for the API.")
    parser.add_argument("--endpoint", required=True, help="The API endpoint to test (e.g., /players).")
    parser.add_argument("--params", nargs='*', help="Query parameters as key=value pairs (e.g., search=LeBron season=2023).")

    args = parser.parse_args()

    # Convert params from list of 'key=value' to a dict
    query_params = {}
    if args.params:
        for param in args.params:
            key, value = param.split('=', 1)
            query_params[key] = value

    asyncio.run(test_api_call(args.api_key, args.base_url, args.endpoint, query_params))
