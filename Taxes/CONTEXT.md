


Taxes/
├── .env                   # Your credentials (never commit this!)
├── requirements.txt
├── certs/
│   ├── fiel.cer           # Your e.firma certificate
│   ├── fiel.key           # Your e.firma private key
│   └── fiel_password.txt  # Your e.firma password
├── data/
│   ├── zips/              # Raw downloaded packages
│   └── xmls/              # Extracted CFDI XMLs
└── module1/
    ├── __init__.py
    ├── downloader.py      # SAT CFDI download logic
    ├── parser.py          # XML → Python data structures
    ├── main.py            # Entry point
    └── request_cache.py   # Zips cache
