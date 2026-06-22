import csv
import io
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
import soundfile as sf

from .config import POLLY_OGG_SAMPLE_RATES_BY_ENGINE, REGION


def load_aws_credentials():
    project_root = Path(__file__).resolve().parents[1]
    search_paths = [
        project_root / "rootkey.csv",
        Path(sys.executable).with_name("rootkey.csv"),
    ]

    credentials_path = next((path for path in search_paths if path.exists()), None)
    if credentials_path is None:
        raise FileNotFoundError(
            "Missing AWS credentials file. Place rootkey.csv in the project root "
            "or next to the built executable."
        )

    with credentials_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        row = next(reader)

    return row["Access key ID"], row["Secret access key"]


aws_access_key_id, aws_secret_access_key = load_aws_credentials()
polly = boto3.client(
    "polly",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=REGION
)


def synthesize_polly_ogg(text, engine):
    last_error = None
    sample_rates = POLLY_OGG_SAMPLE_RATES_BY_ENGINE[engine]

    for sample_rate in sample_rates:
        try:
            response = polly.synthesize_speech(
                Text=text,
                VoiceId="Justin",
                OutputFormat="ogg_vorbis",
                SampleRate=str(sample_rate),
                Engine=engine
            )
            ogg_bytes = response["AudioStream"].read()
            audio, decoded_sample_rate = sf.read(
                io.BytesIO(ogg_bytes),
                dtype="float32",
                always_2d=False
            )
            return audio, decoded_sample_rate
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code != "InvalidSampleRateException":
                raise
            last_error = exc

    raise RuntimeError(
        f"Polly rejected all configured OGG sample rates for {engine}: "
        f"{', '.join(str(rate) for rate in sample_rates)}."
    ) from last_error
