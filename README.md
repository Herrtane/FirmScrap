# FirmScrap: An Efficient Firmware Collection Tool for the FirmAware Framework

## Overview

FirmScrap is a firmware collection tool designed with a metadata-first approach (It is part of the FirmAware framework). Instead of downloading firmware images immediately, the tool first collects metadata — including download links — and stores it in structured JSON files. This separation between metadata collection and the actual download process allows users to update or extend their datasets without repeatedly downloading the same files.

## Target Vendor

- D-Link
- Foscam
- MOXA
- TpLink
- Trendnet
- Ubiquiti
- Netgear

Note: Although IPTime and Zyxel are included in the collected dataset of this study, they were excluded from the analysis. Accordingly, the corresponding scraping modules are not included in this release.


## Key Advantage

By decoupling metadata acquisition from the download phase, FirmScrap prevents redundant downloads when refreshing or expanding datasets.

## Usage Scenario

For example, users can run FirmScrap to generate JSON metadata for all available firmware of a vendor. Later, when the dataset needs to be updated, only the metadata is re-collected, and downloads are performed  using the updated JSON files.

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

## Usage

1. Execute FirmScrap_[Vendor]_json_creator.py. It will create the json file which contains the metadata and download links of the vendor's firmware.
2. Execute FirmScrap_downloader.py. It will need the json file. The downloader will download the actual firmware by parsing the json file.

## Note on Dataset

The dataset collected with this tool may differ from that used in the paper, as factors such as collection time, website changes, or tool updates can affect the number of samples.
Our team continues to improve the code to enable broader and more effective dataset collection.

## Contact

If you have any question or issue, please contact to me.

herrtane@korea.ac.kr








