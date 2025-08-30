# FirmScrap: An Efficient Firmware Collection Tool for the FirmAware Framework

## Overview

FirmScrap is a firmware collection tool designed with a metadata-first approach. Instead of downloading firmware images immediately, the tool first collects metadata — including download links — and stores it in structured JSON files. This separation between metadata collection and the actual download process allows users to update or extend their datasets without repeatedly downloading the same files.

## Key Advantage

By decoupling metadata acquisition from the download phase, FirmScrap prevents redundant downloads when refreshing or expanding datasets, significantly reducing bandwidth usage and storage overhead.

## Usage Scenario

For example, users can run FirmScrap to generate JSON metadata for all available firmware of a vendor. Later, when the dataset needs to be updated, only the metadata is re-collected, and downloads are performed selectively using the existing JSON records. This workflow ensures reproducibility and efficiency in large-scale firmware studies.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Herrtane/FirmScrap.git
   cd FirmScrap
   ```

2. Create and activate a virtual environment (recommended):
    ```
    python3 -m venv venv
    source venv/bin/activate    # On Linux/Mac
    venv\Scripts\activate       # On Windows
    ```

3. Install dependencies:
    ```
    pip install -r requirements.txt
    ```