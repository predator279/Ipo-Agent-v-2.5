import requests
from bs4 import BeautifulSoup
import pandas as pd

def test_aggregator():
    url = "https://ipowatch.in/ipo-grey-market-premium-latest-gmp/"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    print(f"Status Code: {resp.status_code}")
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    tables = soup.find_all('table')
    print(f"Found {len(tables)} tables")
    if tables:
        df = pd.read_html(str(tables[0]))[0]
        print(df.head())

if __name__ == "__main__":
    test_aggregator()
