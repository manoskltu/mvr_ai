# MVR Offer Tool

An AI-powered system that accelerates customer offer generation for a steel fabrication and welding company. The tool processes incoming emails containing construction drawings (offertförfrågning — request for quote), automatically identifies required steel profiles and quantities, and produces a structured Excel spreadsheet ready for pricing. The goal is to reduce the manual effort involved in turning a quote request into a material list.

## Features

- Parse incoming `.eml` emails and extract PDF attachments
- Inspect construction drawings to identify steel profiles (e.g. KKR — square/rectangular hollow sections, HSQ — hot-rolled steel)
- Calculate material types, dimensions, and quantities from drawings
- Generate Excel offer documents with material lists via openpyxl
- Web interface for monitoring and triggering the pipeline

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3 |
| Web framework | Flask |
| Template engine | Jinja2 |
| Excel generation | openpyxl |
| Testing | pytest |
| Build automation | GNU Make |

## Getting Started

### Prerequisites

- Python 3.10 or newer
- GNU Make

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd mvr-offer-tool

# Create virtual environment and install dependencies
make setup
```

### Running the development server

```bash
# Start on default host (127.0.0.1) and port (5000)
make run

# Start with debug mode enabled
make run DEBUG=1

# Start on a custom port
make run PORT=8080
```

### Running tests

```bash
make test
```

### Other useful targets

```bash
make help          # Show all available targets
make clean         # Remove __pycache__, .pytest_cache, .hypothesis
make clean-venv    # Remove the virtual environment
```

## Project Structure

```
mvr-offer-tool/
├── app.py                 Flask application with factory function
├── templates/
│   ├── base.html          Base Jinja2 template (HTML skeleton)
│   └── index.html         Landing page
├── static/
│   ├── css/
│   │   └── style.css      Base styles
│   └── js/
│       └── main.js        Client-side JavaScript
├── tests/                 pytest test suite
├── assets/                Example business data (emails, drawings)
├── Makefile               Developer workflow automation
├── requirements.txt       Python dependencies
└── README.md              This file
```

## Pipeline Overview

The offer generation pipeline transforms a raw customer email into a priced material list:

```
Email received (.eml)
  → Extract attachments (PDFs, ZIP archives, drawings)
    → Investigate drawings (identify steel profiles, dimensions, quantities)
      → Calculate material requirements
        → Generate Excel offer document (material type, amount, price)
```

**Key terms:**

- **Offertförfrågning** — Request for quote; the incoming email from a customer asking for pricing on metalwork
- **KKR** (Konstruktionsrör Kvadratiska/Rektangulära) — Square or rectangular hollow steel sections
- **HSQ** — Hot-rolled steel profiles

The pipeline handles heterogeneous input: PDF construction drawings, email body text in Swedish, ZIP archives of drawing sets, and various naming conventions.

## License

*License information to be added.*
